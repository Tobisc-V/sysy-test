import docker
from docker.models.containers import Container
import os
import subprocess
from logger import printLog

from public import *

debug_container = False # if true, containers will not be removed after finished.

def wrap_cmd(cmd: str) -> str:
    return '/bin/sh -c "{0}"'.format(cmd.replace("\"", "\\\""))

def container_wait(container: Container, name: str):
    try:
        exit = container.wait(timeout=TimeoutSecs)
    except Exception as e:
        try:
            container.kill()
        except:
            pass
        raise e
    finally:
        if not debug_container:
            container.remove()
    if exit['Error'] is not None:
        raise Exception('{name}: container exit with error {err}'.format(name=name, err=exit['Error']))
    elif exit['StatusCode'] != 0:
        raise Exception('{name}: container exit with code {code}'.format(name=name, code=exit['StatusCode'])) # you should see logs dir for further information

JavaImage = 'openjdk:17-oracle'

CmdBuildCompiler = ' \
    javac -d target -encoding \'utf-8\' {cp} @target/src.txt; r=$?; if [ $r -ne 0 ]; then exit $r; fi; \
    cd target; echo \'**\' > .gitignore; mkdir -p META-INF; \
    echo -e \'Manifest-Version: 1.0\\r\\nClass-Path: {libs}\\r\\nMain-Class: Compiler\\r\\n\\r\\n\' > META-INF/MANIFEST.MF; \
    jar -cvfm compiler.jar META-INF/MANIFEST.MF *'

CmdCompileLLVM  = 'java {jvm} -jar compiler.jar -emit-llvm -o test.ll test.sy {opt} 2>/output/compile.log; r=$?; cp test.ll /output/; \
    exit $r'.format(jvm=JvmOptions, opt=OptOptions)
CmdCompileARM   = 'java {jvm} -jar compiler.jar -S -o test.S test.sy {opt} 2>/output/compile.log; r=$?; cp test.S /output/; \
    exit $r'.format(jvm=JvmOptions, opt=OptOptions)
CmdCompileRISCV = 'java {jvm} -jar compiler.jar -S -o test.S test.sy {opt} 2>/output/compile.log; r=$?; cp test.S /output/; \
    exit $r'.format(jvm=JvmOptions, opt=OptOptions)
CmdCompileAll   = 'java {jvm} -jar compiler.jar -emit-llvm -o test.ll -S -o test.S test.sy {opt} 2>/output/compile.log; r=$?; cp test.S test.ll /output/; \
    exit $r'.format(jvm=JvmOptions, opt=OptOptions)

CmdCompileAndRunInterpreter = 'java {jvm} -jar compiler.jar -I test.sy {opt} < input.txt >/output/output.txt 2>/output/perf.txt'.format(jvm=JvmOptions, opt=OptOptions)

SysyImage = "sysy:tobisc"
CmdGenElf = 'ARCH={arch} sysy-asm2elf.sh test.S 2>/output/genelf.log'
CmdRunLLVM = 'sysy-run-llvm.sh test.ll <input.txt >output.txt 2>/output/perf.txt; r=$?; \
    if [ ! -z "$(tail -c 1 output.txt)" ]; then echo >> output.txt; fi; echo $r >> output.txt; cp output.txt /output/'
CmdRunQemu = 'ARCH={arch} sysy-run-elf.sh test.elf <input.txt >output.txt 2>/output/perf.txt; r=$?; \
    if [ ! -z "$(tail -c 1 output.txt)" ]; then echo >> output.txt; fi; echo $r >> output.txt; cp output.txt /output/'

# 构建编译器, project_path 和 artifact_path 均为主机的路径 (使用 -v 选项挂载)
def build_compiler(client: docker.DockerClient, source_path: str, artifact_path: str, library_path: str) -> bool:
    container_name = 'compiler_{0}_build'.format(os.getpid())
    # cmd = '/bin/sh -ce "cd src; ls -la"'
    printLog('building compiler ......')
    # 首先在 src 下生成 src.txt。这样可以避免在容器中执行 find 命令（我发现 find 命令不可用）
    with open(os.path.join(artifact_path, 'src.txt'), 'w') as fp:
        subprocess.run(['find', 'src', '-type', 'f', '-name', '*.java'], stdout=fp, cwd=os.path.dirname(source_path)).check_returncode()
    libs = ''
    cp = ''
    volumes = {
        os.path.realpath(source_path): {'bind': '/project/src', 'mode': 'ro'},
        os.path.realpath(artifact_path): {'bind': '/project/target', 'mode': 'rw'}
    }
    if library_path:
        __ret = subprocess.run(['find', '.', '-type', 'f', '-name', '*.jar'], stdout=subprocess.PIPE, cwd=library_path)
        __ret.check_returncode()
        libs = ' '.join([os.path.join('/project/lib', x.decode('utf-8').strip()) for x in __ret.stdout.splitlines()])
        cp = '-cp ' + ':'.join([os.path.join('/project/lib', x.decode('utf-8').strip()) for x in __ret.stdout.splitlines()])
        volumes[os.path.realpath(library_path)] = {'bind': '/project/lib', 'mode': 'ro'}
    container: Container = client.containers.run(JavaImage, command=wrap_cmd(CmdBuildCompiler.format(libs=libs, cp=cp)),
        detach=True, name=container_name, working_dir='/project', volumes=volumes, mem_limit=MemoryLimit)
    container_wait(container, 'build_compiler')
    printLog('compiler build finished.')

def compile_testcase(client: docker.DockerClient, case_fullname: str, compiler_path: str, sy_path: str, output_path: str, lib_path: str='', type: str='arm'):
    container_name = 'compiler_{pid}_compile_{type}_{name}'.format(pid=os.getpid(), type=type, name=case_fullname.replace('/', '_'))
    printLog('{0} - compiling'.format(case_fullname))
    if type == 'llvm':
        cmd = CmdCompileLLVM
    elif type == 'arm':
        cmd = CmdCompileARM
        if EmitLLVM:
            cmd = CmdCompileAll
    elif type == 'riscv':
        cmd = CmdCompileRISCV
    else:
        raise Exception("compile type {0} not support yet".format(type))
    volumes = {
        os.path.realpath(compiler_path): {'bind': '/compiler/compiler.jar', 'mode': 'ro'},
        os.path.realpath(sy_path): {'bind': '/compiler/test.sy', 'mode': 'ro'},
        os.path.realpath(output_path): {'bind': '/output/', 'mode': 'rw'}
    }
    if lib_path:
        volumes[os.path.realpath(lib_path)] = {'bind': '/project/lib', 'mode': 'ro'}
    container: Container = client.containers.run(JavaImage, command=wrap_cmd(cmd), detach=True, name=container_name,
        working_dir='/compiler', volumes=volumes, mem_limit=MemoryLimit)
    container_wait(container, 'compile')
    printLog('{0} - compile finish.'.format(case_fullname))

def genelf_testcase(client: docker.DockerClient, case_fullname: str, code_path: str, elf_path: str, output_path: str, arch: str):
    container_name = 'compiler_{pid}_genelf_{name}'.format(pid=os.getpid(), name=case_fullname.replace('/', '_'))
    assert code_path.endswith('.S')
    printLog('{0} - elf generate begin'.format(case_fullname))
    container: Container = client.containers.run(image=SysyImage, command=wrap_cmd(CmdGenElf.format(arch=arch)), detach=True, name=container_name, working_dir='/compiler', volumes={
        os.path.realpath(code_path): {'bind': '/compiler/test.S', 'mode': 'ro'},
        os.path.realpath(elf_path): {'bind': '/compiler/test.elf', 'mode': 'rw'},
        os.path.realpath(output_path): {'bind': '/output/', 'mode': 'rw'}
    }, mem_limit=MemoryLimit)
    container_wait(container, 'genelf')
    printLog('{0} - elf generated.'.format(case_fullname))

def run_testcase(client: docker.DockerClient, case_fullname: str, code_path: str, input_path: str, output_path: str, type: str):
    _, extension_name = os.path.basename(code_path).split('.')
    container_name = 'compiler_{pid}_run_{name}'.format(pid=os.getpid(), type=type, name=case_fullname.replace('/', '_'))
    printLog('{0} - running'.format(case_fullname))
    if type == 'llvm':
        cmd = CmdRunLLVM
    elif type == 'qemu-arm':
        cmd = CmdRunQemu.format(arch='arm')
    elif type == 'qemu-riscv':
        cmd = CmdRunQemu.format(arch='riscv')
    else:
        raise Exception("run type {0} not support yet".format(type))
    container: Container = client.containers.run(image=SysyImage, command=wrap_cmd(cmd), detach=True, name=container_name, working_dir='/compiler', volumes={
        os.path.realpath(code_path): {'bind': '/compiler/test.' + extension_name, 'mode': 'ro'},
        os.path.realpath(input_path): {'bind': '/compiler/input.txt', 'mode': 'ro'},
        os.path.realpath(output_path): {'bind': '/output/', 'mode': 'rw'}
    }, mem_limit=MemoryLimit)
    container_wait(container, 'run')
    printLog('{0} - run finish.'.format(case_fullname))

def run_interpreter(client: docker.DockerClient, case_fullname: str, compiler_path: str, sy_path: str, input_path: str, output_path: str, lib_path: str=''):
    _, extension_name = os.path.basename(sy_path).split('.')
    assert extension_name == 'sy'
    container_name = 'compiler_{pid}_interpret_{name}'.format(pid=os.getpid(), name=case_fullname.replace('/', '_'))
    printLog('{0} - interpret begin.'.format(case_fullname))
    volumes={
        os.path.realpath(compiler_path): {'bind': '/compiler/compiler.jar', 'mode': 'ro'},
        os.path.realpath(sy_path): {'bind': '/compiler/test.sy', 'mode': 'ro'},
        os.path.realpath(input_path): {'bind': '/compiler/input.txt', 'mode': 'ro'},
        os.path.realpath(output_path): {'bind': '/output/', 'mode': 'rw'}
    }
    if lib_path:
        volumes[os.path.realpath(lib_path)] = {'bind': '/project/lib', 'mode': 'ro'}
    container: Container = client.containers.run(image=JavaImage, command=wrap_cmd(CmdCompileAndRunInterpreter), detach=True,
        name=container_name, working_dir='/compiler', volumes=volumes, mem_limit=MemoryLimit)
    container_wait(container, 'interpret')
    printLog('{0} - interpret done.'.format(case_fullname))
