"""Single entry for both installed Python and bundled GUI runtime."""
import os,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
if (ROOT/'gui'/'tcl').is_dir():
    os.environ['TCL_LIBRARY']=str(ROOT/'gui'/'tcl'/'tcl8.6')
    os.environ['TK_LIBRARY']=str(ROOT/'gui'/'tcl'/'tk8.6')
if __name__=='__main__':
    try:
        from assistant_app import main
        main()
    except Exception:
        error=traceback.format_exc()
        folder=ROOT/'.local';folder.mkdir(exist_ok=True)
        (folder/'startup-error.log').write_text(error,encoding='utf-8')
        import ctypes
        ctypes.windll.user32.MessageBoxW(None,'启动失败。请运行 SelfCheck.cmd，或检查 .local/startup-error.log。\n不要删除自己的进度记录。','统一推进助手',16)
        raise
