"""User-requested standard UAC launch. Never accepts/bypasses the consent prompt."""
import ctypes,os,subprocess,sys
from pathlib import Path
RELAUNCH_FLAG='--elevation-requested'

class ElevationApi:
    def __init__(self):
        if os.name!='nt':raise RuntimeError('This application requires Windows')
        from ctypes import wintypes as w
        self.shell=ctypes.WinDLL('shell32',use_last_error=True)
        self.shell.IsUserAnAdmin.argtypes=[];self.shell.IsUserAnAdmin.restype=w.BOOL
        self.shell.ShellExecuteW.argtypes=[w.HWND,w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,ctypes.c_int]
        self.shell.ShellExecuteW.restype=ctypes.c_void_p
    def is_admin(self):return bool(self.shell.IsUserAnAdmin())
    def launch(self,exe,parameters,cwd):
        ctypes.set_last_error(0)
        result=self.shell.ShellExecuteW(None,'runas',exe,parameters,cwd,1)
        return int(result or 0),ctypes.get_last_error()

def ensure_administrator(entry,arguments,api=None,executable=None):
    arguments=list(arguments)
    if '--ui-check' in arguments or '--ui-exercise' in arguments:return 'continue'
    api=api or ElevationApi()
    if api.is_admin():return 'continue'
    if RELAUNCH_FLAG in arguments:raise RuntimeError('管理员启动未完成；不会反复弹出授权或继续运行任务。')
    entry=Path(entry).resolve()
    parameters=subprocess.list2cmdline(['-B','-X','utf8',str(entry),*arguments,RELAUNCH_FLAG])
    result,error=api.launch(str(executable or sys.executable),parameters,str(entry.parent))
    if result>32:return 'relaunched'
    if error==1223:return 'cancelled'
    raise RuntimeError('管理员启动失败（WinError '+str(error or result)+'）；没有启动任务。')
