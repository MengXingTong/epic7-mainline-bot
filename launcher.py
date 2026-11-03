"""Safe local launcher. No gameplay input unless start is explicitly confirmed."""
from __future__ import annotations
import json, os, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'vendor'))
from ui_text import ChineseArgumentParser,error_text,scene_name
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')

def load_config():
    p=ROOT/'config.json'
    return json.loads((p if p.exists() else ROOT/'config.example.json').read_text(encoding='utf-8-sig'))

def find_adb(configured=''):
    candidates=[]
    if configured: candidates.append(Path(os.path.expandvars(configured)).expanduser())
    found=shutil.which('adb')
    if found:candidates.append(Path(found))
    roots=[]
    if os.environ.get('MUMU_HOME'): roots.append(Path(os.environ['MUMU_HOME']))
    for drive in ('C:','D:','E:','F:'):
        for folder in ('MuMuPlayerGlobal','MuMuPlayer-12.0','MuMuPlayer','Program Files/Netease/MuMuPlayerGlobal','Program Files/Netease/MuMuPlayer-12.0','Program Files/NetEase/MuMuPlayerGlobal'):
            roots.append(Path(drive+'/')/folder)
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER,winreg.HKEY_LOCAL_MACHINE):
            for keyname in (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
                try:
                    with winreg.OpenKey(hive,keyname) as key:
                        for i in range(winreg.QueryInfoKey(key)[0]):
                            try:
                                with winreg.OpenKey(key,winreg.EnumKey(key,i)) as entry:
                                    name=winreg.QueryValueEx(entry,'DisplayName')[0]
                                    if 'mumu' not in name.lower(): continue
                                    try: roots.append(Path(winreg.QueryValueEx(entry,'InstallLocation')[0]))
                                    except OSError: pass
                            except OSError: pass
                except OSError: pass
    except ImportError: pass
    for base in roots:
        for suffix in ('nx_main/adb.exe','nx_device/15.0/shell/adb.exe','nx_device/12.0/shell/adb.exe','shell/adb.exe','adb.exe'):
            candidates.append(base/suffix)
    return next((p.resolve() for p in candidates if p.is_file()),None)

def adb(cfg,*args):
    p=subprocess.run([cfg['adb'],*map(str,args)],capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    if p.returncode: raise RuntimeError(p.stderr.decode('utf8',errors='replace') or '模拟器调试命令执行失败。')
    return p.stdout.decode('utf8',errors='replace')

def setup():
    cfg=load_config();path=find_adb(cfg.get('adb',''))
    if not path:raise RuntimeError('未找到MuMu自带的adb.exe。复制config.example.json为config.json，填写adb绝对路径。')
    cfg['adb']=str(path)
    if not cfg.get('serial'):raise RuntimeError('请先填写config.json中的serial（MuMu实例ADB地址）。')
    if not cfg.get('package'):raise RuntimeError('请先填写游戏的Android包名package。')
    (ROOT/'config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf8')
    adb(cfg,'connect',cfg['serial'])
    rows=[line.split() for line in adb(cfg,'devices').splitlines()[1:] if line.strip()]
    online=[row[0] for row in rows if len(row)>1 and row[1]=='device']
    if cfg['serial'] not in online:raise RuntimeError('指定模拟器没有连接成功。请核对ADB地址和MuMu的ADB设置。')
    if cfg.get('strict_single_device',True) and len(online)>1:
        raise RuntimeError('检测到多个ADB设备。请确认serial准确后，在config.json中将strict_single_device改为false。')
    activity=adb(cfg,'-s',cfg['serial'],'shell','dumpsys','activity','activities')
    active=[line for line in activity.splitlines() if 'topResumedActivity' in line or 'mResumedActivity' in line]
    if not any(cfg['package'] in line for line in active):raise RuntimeError('请先在指定MuMu实例中打开对应游戏；当前前台包名与配置不一致。')
    return cfg

def preview():
    setup()
    from runner import Runner,classify
    r=Runner();f=r.capture();mode=classify(f)
    print('当前画面识别：',scene_name(mode))
    print('预览已保存在 latest.png 和 latest-ocr.json；本检查没有发送点击或按键。')
    if mode not in ('lobby','map','support','team'):
        raise RuntimeError('请先进入大厅或主线/准备界面。未知弹窗、网络错误和其他页面不会直接开刷。')
    return r

def self_test():
    if sys.version_info[:2]!=(3,12):raise RuntimeError('本版本离线运行库要求Python 3.12。')
    import cv2,numpy as np
    from rapidocr_onnxruntime import RapidOCR
    from runner import Frame,classify
    image=np.full((160,640,3),255,np.uint8)
    cv2.putText(image,'TEST 123',(25,105),cv2.FONT_HERSHEY_SIMPLEX,2,(0,0,0),3)
    results,_=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)(image)
    if not results:raise RuntimeError('OCR模型自检失败')
    words=[([[600,300],[1100,300],[1100,350],[600,350]],'是否使用道具兑换体力',.999)]
    if classify(Frame(np.zeros((900,1600,3),np.uint8),words))!='resource_stop':raise RuntimeError('资源拦截自检失败')
    print('自检通过：运行库、图像处理、文字识别和资源消耗拦截检查正常。')
    print('运行库版本：',sys.version.split()[0]);print('解释器路径：',sys.executable)
    print('文字识别模块：',__import__('rapidocr_onnxruntime').__file__)
    print('文字识别结果：',[x[1] for x in results])
    return 0

def spawn_supervisor():
    with (ROOT/'launcher.log').open('a',encoding='utf8') as out:
        p=subprocess.Popen([sys.executable,'-B','-X','utf8',str(ROOT/'supervisor.py')],cwd=str(ROOT),stdout=out,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    print('已请求后台启动，进程编号：',p.pid,'；请查看STATUS.md。重复启动有进程锁保护。')

def resume_checked():
    setup()
    from runner import Runner,classify,event
    old=json.loads((ROOT/'state.json').read_text(encoding='utf8')) if (ROOT/'state.json').exists() else None
    if not old or not old.get('terminal'):raise RuntimeError('没有已停止的运行记录；首次用start，运行中不要重复续跑。')
    print('续跑保留所有入场/通关记录，不会清空记录。')
    print('若曾战败或中途停止，先手动完成该关，并在主线地图选中这一个带绿色通关勾的节点。')
    if input('确认检查并续跑请输入“继续”：').strip() not in ('继续','RESUME'):print('已取消。');return 0
    r=Runner();f=r.capture();mode=classify(f)
    if mode not in ('lobby','map','support','team'):raise RuntimeError('当前画面不是可安全续跑的大厅/地图/准备页，保持停止。')
    active=r.s.get('active')
    if active:
        if mode!='map':raise RuntimeError('有未结算入场记录。请先手动完成，再在地图选中已通关节点；不允许重复入场。')
        node,rows,proof=r.map_ticket(f)
        if not node or node['key']!=active['key'] or proof!='已通关绿色勾':
            raise RuntimeError('未确认原关卡的绿色通关标记，不会清空记录或重开。')
        key=active['key'];r.s['active'].update(manual_completed=True,outcome='user_cleared_after_stop')
        r.s['attempted'][key]['manual_cleared_at']=__import__('runner').now()
        r.completed('本地用户要求续跑，地图精确选中原关卡并确认绿色通关勾')
    if (ROOT/'STOP').exists():(ROOT/'STOP').unlink()
    r.s.update(terminal=False,status='正在推进主线',reason='本地用户确认安全续跑；保留全部入场/通关记录')
    r.save();event('local_user_resume',preserved_all_progress=True);spawn_supervisor();return 0

def main():
    ap=ChineseArgumentParser();ap.add_argument('command',choices=['check','start','stop','resume','selftest']);args=ap.parse_args()
    if args.command=='selftest':return self_test()
    if args.command=='resume':return resume_checked()
    if args.command=='stop':
        (ROOT/'STOP').write_text('本机用户请求停止',encoding='utf8')
        print('已请求停止。当前动作结束后停止输入，不关闭游戏。');return 0
    if (ROOT/'STOP').exists():raise RuntimeError('STOP标记存在，保持停止。不要通过删除进度记录强行重试；先检查状态和关卡。')
    if (ROOT/'state.json').exists():
        state=json.loads((ROOT/'state.json').read_text(encoding='utf8'))
        if state.get('terminal') and args.command=='start':raise RuntimeError('已安全停止：'+state.get('reason','请检查STATUS.md')+'。不要清空state.json来重打关卡。')
    preview()
    if args.command=='check':return 0
    print('\n将操作当前MuMu账号，消耗正常入场体力。不会兑换体力或付费续战。')
    print('请确认latest.png是正确账号和界面。不要同时手动操作，也不要跨账号共用此目录。')
    if input('确认启动请输入“开始”：').strip() not in ('开始','START'):print('已取消，未启动。');return 0
    spawn_supervisor()
    return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as e:print('\n停止：'+error_text(e),file=sys.stderr);raise SystemExit(1)
