"""Local worker supervisor: single instance, bounded restart, no game inputs."""
import datetime as dt,json,msvcrt,os,subprocess,sys,time
from pathlib import Path
CODE_ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(CODE_ROOT))
from runtime_paths import data_root
ROOT=data_root()

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
    except OSError: log('已有守护进程持有进度锁；当前进程退出。'); return
    (ROOT/'supervisor.pid').write_text(str(os.getpid()),encoding='ascii')
    restarts=[]
    try:
        while not (ROOT/'STOP').exists():
            state=read_state()
            if state.get('terminal'): log('保留停止状态：'+state.get('status','')); break
            env=os.environ.copy(); env['PYTHONIOENCODING']='utf-8'
            with (ROOT/'worker.stdout.log').open('a',encoding='utf8') as out:
                child=subprocess.Popen([sys.executable,'-B','-X','utf8',str(CODE_ROOT/'runner.py')],stdout=out,stderr=subprocess.STDOUT,env=env,cwd=str(ROOT),creationflags=subprocess.CREATE_NO_WINDOW)
                log('已启动工作进程，进程编号：'+str(child.pid)); start=time.time()
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
                        log('工作进程超过 180 秒未更新心跳；仅终止自己启动的子进程。'); child.terminate()
                        try: child.wait(timeout=15)
                        except subprocess.TimeoutExpired: child.kill()
                        break
                child.wait(); log('工作进程已退出，退出码：'+str(child.returncode))
            if read_state().get('terminal') or (ROOT/'STOP').exists(): break
            restarts=[x for x in restarts if time.time()-x<600]; restarts.append(time.time())
            if len(restarts)>3: log('已超过进程重启上限；等待人工检查。'); break
            time.sleep(5)
    finally:
        log('守护进程已停止。'); lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1); lock.close()
if __name__=='__main__': main()
