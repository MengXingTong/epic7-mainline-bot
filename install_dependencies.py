"""Source-package dependency installer: direct first, proxy fallback only on failure."""
from pathlib import Path
import os,subprocess,sys
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
root=Path(__file__).resolve().parent
if sys.version_info[:2]!=(3,12):raise SystemExit('本项目需要使用 Python 3.12 64 位运行库。')
base=[sys.executable,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:','--target',str(root/'vendor'),'-r',str(root/'requirements.txt')]
env=os.environ.copy()
for k in list(env):
    if k.lower() in ('http_proxy','https_proxy','all_proxy'):env.pop(k,None)
env['NO_PROXY']='*';env['no_proxy']='*'
print('正在绕开代理直接下载……')
p=subprocess.run(base+['--proxy',''],env=env)
if p.returncode:
    print('直连下载失败；正在使用原有代理和环境设置重试……')
    p=subprocess.run(base,env=os.environ.copy())
raise SystemExit(p.returncode)
