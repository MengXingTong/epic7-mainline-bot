"""Source-package dependency installer: direct first, proxy fallback only on failure."""
from pathlib import Path
import os,subprocess,sys
root=Path(__file__).resolve().parent
if sys.version_info[:2]!=(3,12):raise SystemExit('Use Python 3.12 x64 for this package.')
base=[sys.executable,'-m','pip','install','--disable-pip-version-check','--only-binary=:all:','--target',str(root/'vendor'),'-r',str(root/'requirements.txt')]
env=os.environ.copy()
for k in list(env):
    if k.lower() in ('http_proxy','https_proxy','all_proxy'):env.pop(k,None)
env['NO_PROXY']='*';env['no_proxy']='*'
print('Trying direct download without proxy...')
p=subprocess.run(base+['--proxy',''],env=env)
if p.returncode:
    print('Direct download failed; retrying with the original proxy/environment settings...')
    p=subprocess.run(base,env=os.environ.copy())
raise SystemExit(p.returncode)
