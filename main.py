import os, json
from concurrent.futures import ThreadPoolExecutor

from const import *
from public import *
from util import pretty_result, walk_testcase, display_result, archive_source
from tasks import build_compiler
from judge import test_one_case
from rpi import setup_rpi, wait_rpi_all

# 初始化树莓派
setup_rpi(RpiAddresses)

if RebuildCompiler:
    build_compiler(DockerClient, CompilerSrc, CompilerBuild, CompilerLib)

if CacheSource:
    archive_source(CompilerSrc, os.path.join(logDir, "src.tar.gz"))

testcases = walk_testcase(TestcaseBaseDir, TestcaseSelect)

# # 使用线程池运行测试点
with ThreadPoolExecutor(max_workers=NumParallel) as pool:
    pool.map(test_one_case, testcases)

wait_rpi_all()

with open(os.path.join(logDir, 'result_' + logName + '.html'), 'w') as fp:
    fp.write(display_result(results, title=logName))

with open(os.path.join(logDir, 'result_' + logName + '.json'), 'w') as fp:
    json.dump(results, fp=fp)

result = pretty_result(results)
print(result)
with open(os.path.join(logDir, 'result_' + logName + '.txt'), 'w') as fp:
    fp.write(result)

print("log name: {0}".format(logName))
# close log file
logFile.close()