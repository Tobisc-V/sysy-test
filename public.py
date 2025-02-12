import docker
import os, sys, json, shutil
from datetime import datetime

DockerClient = docker.from_env()

ConfigFile = 'config.json'

if len(sys.argv) >= 2:
    ConfigFile = sys.argv[1]

with open(ConfigFile, 'r') as fp:
    config: dict = json.load(fp)

def get_config(key: str, default=None):
    if default is None:
        return config[key]
    return config.get(key, default)

CompilerSrc = config['compiler-src']      # path to the compiler source code (./src/)
CompilerLib = get_config('compiler-lib', "")  # path to the compiler library (./lib/)
CompilerBuild = config['compiler-build']  # path to compiler build artifact
CompilerFileName = 'compiler.jar'  # name of executable jar

TestcaseBaseDir = config['testcase-base']
TestcaseSelect = config['testcase-select']
NumParallel = config['num-parallel']

RebuildCompiler = config['rebuild-compiler']

RunType = config['run-type']

CacheSource = get_config('cache-source', False)
RpiAddresses = get_config('rpi-addresses', [])
LogDirBase = get_config('log-dir', 'logs')
LogDirHostBase = get_config('log-dir-host', LogDirBase)
TimeoutSecs = get_config('timeout', 60)

JvmOptions = get_config('jvm-options', "")
OptOptions = get_config('opt-options', "")

MemoryLimit = get_config('memory-limit', '256m')
EmitLLVM = get_config('emit-llvm', False)

logName = datetime.now().strftime('%Y_%m_%d_%H_%M_%S') + "_" + str(os.getpid())
logDir = os.path.realpath(os.path.join(LogDirBase, logName))
logDirHost = os.path.realpath(os.path.join(LogDirHostBase, logName))

os.makedirs(logDir)
shutil.copy(ConfigFile, os.path.join(logDir, os.path.basename(ConfigFile)))

logFile = open(os.path.join(logDir, logName + '.log'), 'a')

results = [] # {series, name, verdict, comment, perf, stdin, stdout, answer}
