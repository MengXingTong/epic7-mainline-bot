"""Control only the current unified worker; never starts/restarts a stopped run."""
import argparse,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from assistant_config import HOME,read_json,atomic_json

def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=('stop','pause','resume'));a=ap.parse_args()
    active=read_json(HOME/'active-run.json',{})
    if not active:print('No active unified worker.');return
    folder=Path(active['run_dir']).resolve()
    if folder.parent!=(HOME/'runs').resolve():raise ValueError('Run folder is outside the managed workspace')
    status=read_json(folder/'status.json',{})
    if status.get('run_id')!=active['run_id']:raise ValueError('Worker identity mismatch')
    if a.action=='resume' and status.get('mode')!='paused':raise ValueError('Only an already-paused worker can resume; no restart performed')
    atomic_json(folder/'control.json',{'run_id':active['run_id'],'action':'run' if a.action=='resume' else a.action})
    print('Requested '+a.action+'; game and history are unchanged.')

if __name__=='__main__':main()
