"""Local worker supervisor: single instance, bounded restart, no game inputs."""
import datetime as dt,json,msvcrt,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def read_state():
    try: return json.loads((ROOT/'state.json').read_text(encoding='utf8'))
    except Exception: return {}
def log(message):
    with (ROOT/'supervisor.log').open('a',encoding='utf8') as f: f.write(dt.datetime.now().isoformat(timespec='seconds')+' '+message+'\n')
def main():
    lock=(ROOT/'supervisor.lock').open('a+b')
    if lock.seek(0,os.SEEK_END)==0: lock.write(b'0'); lock.flush()
    lock.seek(0)
    try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    except OSError: log('Existing supervisor owns lock; exit.'); return
    (ROOT/'supervisor.pid').write_text(str(os.getpid()),encoding='ascii')
    restarts=[]
    try:
        while not (ROOT/'STOP').exists():
            state=read_state()
            if state.get('terminal'): log('Terminal status retained: '+state.get('status','')); break
            env=os.environ.copy(); env['PYTHONIOENCODING']='utf-8'
            with (ROOT/'worker.stdout.log').open('a',encoding='utf8') as out:
                child=subprocess.Popen([sys.executable,'-B','-X','utf8',str(ROOT/'runner.py')],stdout=out,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
                log('Started worker pid '+str(child.pid)); start=time.time()
                while child.poll() is None:
                    time.sleep(10)
                    if (ROOT/'STOP').exists():
                        # Give the worker time to observe the stop marker and retain evidence.
                        try: child.wait(timeout=35)
                        except subprocess.TimeoutExpired: child.terminate()
                        break
                    path=ROOT/'state.json'
                    last=path.stat().st_mtime if path.exists() else start
                    if time.time()-max(last,start)>180:
                        log('Worker heartbeat stale >180s; terminate only own child process'); child.terminate()
                        try: child.wait(timeout=15)
                        except subprocess.TimeoutExpired: child.kill()
                        break
                child.wait(); log('Worker exited '+str(child.returncode))
            if read_state().get('terminal') or (ROOT/'STOP').exists(): break
            restarts=[x for x in restarts if time.time()-x<600]; restarts.append(time.time())
            if len(restarts)>3: log('Restart budget exceeded; awaiting agent inspection.'); break
            time.sleep(5)
    finally:
        log('Supervisor stopped.'); lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1); lock.close()
if __name__=='__main__': main()
