"""One private worker for mainline/Abyss on MuMu/PC. No GUI, no supervisor retries."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, time, traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from assistant_config import CODE_ROOT,atomic_json,read_json,validate_run,reserve_abyss_entry
from task_blockers import TaskAttention
from task_timing import TransitionPacer,next_delay

class StopRun(Exception):pass
class PauseRun(Exception):pass

class Control:
    def __init__(self,request):
        self.request=request;self.folder=Path(request['run_dir']);self.run_id=request['run_id'];self.started=time.monotonic()
        self.last={'mode':'starting','status':'正在连接','scene':'—','wins':0,'task':request['settings']['task'],'client':request['target']['client']}
    def check(self):
        command=read_json(self.folder/'control.json',{})
        if command.get('run_id')!=self.run_id or command.get('action')=='stop':raise StopRun()
        if command.get('action')=='pause':raise PauseRun()
    def status(self,status=None,**values):
        if values.get('mode')=='blocked':values.setdefault('warning','')
        self.last.update(values)
        if status is not None:self.last['status']=status
        self.last.update(elapsed=int(time.monotonic()-self.started),updated_at=time.time(),run_id=self.run_id)
        atomic_json(self.folder/'status.json',self.last)
        print(json.dumps(dict(kind='status',**self.last),ensure_ascii=False),flush=True)
    def log(self,text):
        print(json.dumps({'kind':'log','text':text},ensure_ascii=False),flush=True)
    def preview(self,image):
        from PIL import Image
        image=image.copy();image.thumbnail((560,315),Image.Resampling.BILINEAR)
        p=self.folder/'preview.tmp.png';image.save(p,compress_level=1);os.replace(p,self.folder/'preview.png')
    def sleep(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.check();time.sleep(min(.2,max(0,end-time.monotonic())))
    def paused(self):
        resume_mode=self.last.get('mode','starting')
        self.status('已暂停；继续时重新截图，不重用旧坐标。',mode='paused')
        while True:
            try:self.check();self.status('已恢复，正在刷新当前状态。',mode=resume_mode);return
            except PauseRun:time.sleep(.2)

    def attention(self,exc):
        # Never write the control file: a concurrent Stop must win over this wait.
        old=read_json(self.folder/'control.json',{}).get('command_id')
        self.status(exc.title+'；'+exc.reason,mode='attention',attention_code=exc.code)
        while True:
            command=read_json(self.folder/'control.json',{})
            if command.get('run_id')!=self.run_id or command.get('action')=='stop':raise StopRun()
            if command.get('action')=='run' and command.get('command_id') and command['command_id']!=old:
                self.status('已继续，正在重新读取当前画面。',mode='run',attention_code='');return
            time.sleep(.2)

class GuardedApi:
    def __init__(self,api,control):self.api=api;self.control=control
    def __getattr__(self,name):return getattr(self.api,name)
    def ready(self,s):self.control.check();return self.api.ready(s)
    def capture(self,s):self.control.check();return self.api.capture(s)
    def point_is_target(self,*args):self.control.check();return self.api.point_is_target(*args)
    def move(self,*args):self.control.check();return self.api.move(*args)
    def button(self,down):
        if down:self.control.check()
        return self.api.button(down)
    def escape(self):self.control.check();return self.api.escape()


def capture_fresh(capture,control,clock=time.monotonic):
    from pc_message_backend import CaptureUnavailable
    since=None
    while True:
        control.check()
        try:
            result=capture()
            if since is not None:control.status('画面已恢复，继续读取当前界面。',mode='run')
            return result
        except CaptureUnavailable:
            now=clock()
            if since is None:since=now
            if now-since>=10:
                control.attention(TaskAttention('capture','暂时取不到游戏画面','请保持游戏窗口未最小化，处理后继续；不会抢焦点或在黑帧上点击。'))
                since=None
            else:
                control.status('切屏期间暂未取得画面，正在重新取图；不点击、不切换前台。',mode='recovering')
                control.sleep(.4)

def discover(settings):
    from pc_backend import Win32Api
    api=Win32Api();targets=[]
    for title in ('第七史诗','第七史詩','Epic Seven'):
        for s in api.windows('',title):
            targets.append(dict(client='pc',hwnd=s.hwnd,pid=s.pid,created=s.created,exe=s.exe,title=title,label=f'桌面端 · PID {s.pid} · {s.width}×{s.height}'))
    from launcher import find_adb
    cfg=settings.setdefault('mumu',{})
    adb=find_adb(cfg.get('adb',''))
    if adb:
        cfg['adb']=str(adb)
        def devices():
            out=subprocess.run([str(adb),'devices'],capture_output=True,timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
            return [p[0] for line in out.stdout.decode('utf-8',errors='replace').splitlines()[1:] if len(p:=line.split())>=2 and p[1]=='device']
        serials=devices()
        if not serials:
            # Local MuMu default only; no network/port scan or arbitrary remote ADB.
            serial=cfg.get('serial') or '127.0.0.1:16384'
            subprocess.run([str(adb),'connect',serial],capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
            serials=devices()
        for serial in serials:
            if cfg.get('serial') and serial!=cfg['serial']:continue
            package=cfg.get('package','com.stove.epic7.google')
            out=subprocess.run([str(adb),'-s',serial,'shell','pm','path',package],capture_output=True,timeout=5,creationflags=subprocess.CREATE_NO_WINDOW)
            if out.returncode or not out.stdout.strip().startswith(b'package:'):continue
            targets.append(dict(client='mumu',serial=serial,package=package,label='MuMu · '+serial+' · ADB后台'))
    return targets


def abyss_run(request,control):
    from abyss_core import Observation,Token,Session,Scene,classify,RunComplete,PauseRequired
    from abyss_templates import TemplateBank
    from assistant_transport import UnifiedTransport
    from rapidocr_onnxruntime import RapidOCR
    import numpy as np
    settings,target=request['settings'],request['target']
    transport=UnifiedTransport(settings,target,control.check)
    ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    bank=TemplateBank(CODE_ROOT/'assets/abyss' if (CODE_ROOT/'portable.json').exists() else CODE_ROOT/'.local/assistant/abyss-assets')
    if not bank.entries and not settings['observe']:raise RuntimeError('缺少本机深渊识别模板，已停止；不会盲点或下载素材。')
    session=Session(limit=int(settings['limit']))
    history_path=Path(request['home'])/'abyss-history.json'
    history=read_json(history_path,{'schema':1,'clients':{}})
    label=target['exe'] if target['client']=='pc' else target['serial']+'|'+target['package']
    from assistant_portable import enabled
    _,state=validate_run(settings,target,allow_reconcile=True)
    if enabled():
        binding=state.get('pc_profile_binding',{})
        if binding:label='account|'+binding['server']+'|'+binding['account_id']
        elif state.get('local_profile_id'):label='profile|'+state['local_profile_id']
    key=hashlib.sha256((('account' if enabled() else target['client'])+'|'+label).encode()).hexdigest()[:24]
    if state.get('local_profile_id'):key=hashlib.sha256(('local_profile|'+state['local_profile_id']).encode()).hexdigest()[:24]
    ledger=history.setdefault('clients',{}).setdefault(key,{'attempted':{},'completed':{}})
    previous=None;stable=0;cooldown=0;cooldown_scene=None;unknown=None
    while True:
        try:
            control.check();snap=capture_fresh(transport.capture,control);image=snap.image
            results,_=ocr(np.array(image)[:,:,::-1].copy());tokens=[]
            for box,text,score in results or []:
                if score<.65:continue
                x=min(p[0] for p in box);y=min(p[1] for p in box);r=max(p[0] for p in box);b=max(p[1] for p in box)
                tokens.append(Token(text,x,y,r-x,b-y,score=float(score)))
            obs=bank.apply(image,Observation(image.width,image.height,tokens,snap.captured_at))
            reading=classify(obs,session.normal_verified or settings['observe'])
            floor_text=f' · 第{reading.floor}层' if reading.floor else ''
            control.preview(image)
            control.status('只读观察，不发送点击' if settings['observe'] else '普通深渊推进中',mode='observe' if settings['observe'] else 'run',scene=reading.scene.value+floor_text,wins=session.wins,expected_floor=session.expected_floor)
            signature=(reading.scene,reading.floor,reading.available_floor)
            stable=stable+1 if previous==signature else 1
            if previous!=signature:control.log('识别：'+reading.scene.value+floor_text)
            previous=signature
            if settings['observe']:
                if request.get('once'):return
                control.sleep(1);continue
            if session.battle_started_at and time.monotonic()-session.battle_started_at>1200:raise PauseRequired('单场超过20分钟，停止等待确认。')
            if reading.scene in (Scene.HARD,Scene.DEFEAT,Scene.BLOCKED,Scene.CAPACITY):session.plan(reading,obs)
            if reading.scene==Scene.UNKNOWN:
                if session.phase in ('battle_opening','battle') and session.battle_started_at:
                    control.status('等待原生自动战斗或过场；不点击技能。');control.sleep(1);continue
                unknown=unknown or time.monotonic()
                if time.monotonic()-unknown>15:raise PauseRequired('界面连续15秒无法确认，不猜测按钮。')
                control.sleep(1);continue
            unknown=None
            if stable<2 or (reading.scene==cooldown_scene and time.monotonic()<cooldown):control.sleep(.4);continue
            if reading.scene==Scene.CLEAR and reading.floor is not None:
                ledger['completed'].setdefault(str(reading.floor),{'observed_clear_at':time.time()})
                atomic_json(history_path,history)
            if reading.scene==Scene.NORMAL and reading.available_floor is not None:
                floor=str(reading.available_floor)
                if floor in ledger['attempted'] and floor not in ledger['completed']:
                    raise TaskAttention('new_floor','请选择下一新层','当前层已有入场记录；请选择游戏中下一可进行层后继续，不回查旧层、不重复入场。')
            action=session.plan(reading,obs)
            if action:
                if request.get('navigation_only') and action.kind=='start_battle':
                    control.status('后台导航验收完成；停在准备页，未开战、未消费体力。',mode='done',scene=reading.scene.value+floor_text,wins=0,navigation_verified=True);return
                if session.last_action_key==action.key and session.action_repeats>=2:raise PauseRequired('同一步两次未变化，停止重复点击。')
                if action.kind=='start_battle':
                    floor=str(session.expected_floor)
                    reserve_abyss_entry(ledger,session.expected_floor,{'requested_at':time.time(),'client':target['client'],'input_mode':settings.get('pc_input')})
                    atomic_json(history_path,history)
                if action.kind=='swipe':transport.swipe(snap)
                else:transport.tap(snap,action.token,action.ordinary_gate)
                session.applied(action);control.log('执行：'+action.name);cooldown=time.monotonic()+2;cooldown_scene=reading.scene;stable=0
            control.sleep(2.5 if reading.scene==Scene.BATTLE else .4)
        except RunComplete as exc:
            if session.last_won_floor is not None:
                ledger['completed'].setdefault(str(session.last_won_floor),{'verified_clear_at':time.time()});atomic_json(history_path,history)
            control.status(str(exc),mode='done',wins=session.wins,scene=Scene.CLEAR.value);return
        except TaskAttention as exc:
            control.attention(exc);previous=None;stable=0;cooldown=0;unknown=None
        except PauseRun:control.paused();previous=None;stable=0


def mainline_run(request,control):
    settings,target=request['settings'],request['target']
    root,state=validate_run(settings,target,allow_reconcile=True)
    cfg=read_json(root/'config.json',{})
    cfg.update(max_battle_seconds=cfg.get('max_battle_seconds',1800),start_policy=settings.get('start_policy','current_screen'),fast_mode=settings.get('fast_mode',True))
    if target['client']=='mumu':
        cfg.update(settings['mumu']);cfg.update(backend='mumu_adb',serial=target['serial'],package=target['package'])
    else:
        cfg.update(backend='stove_pc',pc=dict(game_exe=target['exe'],window_title=target['title'],experimental_input_enabled=True,allow_stretched_client=False,authorization_mode='selected_target'))
    config_file=Path(request['run_dir'])/'runtime-config.json';atomic_json(config_file,cfg)
    os.environ.update(EPIC7_DATA_DIR=str(root),EPIC7_CONFIG_PATH=str(config_file))
    import runner
    runner.ROOT=root
    from runner import Runner,classify
    class ControlledRunner(Runner):
        def ensure_game(self):control.check();return super().ensure_game()
        def adb(self,*args,**kwargs):control.check();return super().adb(*args,**kwargs)
    r=ControlledRunner(observe=True)
    backend=None
    if target['client']=='pc':
        from pc_backend import PcBackend
        from pc_message_backend import MessageWin32Api
        if settings.get('pc_input')!='messages':raise RuntimeError('前台模式已移除。')
        api=MessageWin32Api()
        backend=PcBackend(cfg['pc'],root/'STOP',api=GuardedApi(api,control),read_only=settings['observe'])
        identity={'hwnd':target['hwnd'],'pid':target['pid'],'created':target['created'],'exe':os.path.normcase(os.path.abspath(target['exe']))}
        if not settings['observe']:backend.authorize_selected_target(identity)
        r.pc=backend
    if request.get('preflight_only'):
        frame=r.capture()
        control.status('主线窗口与进度预检通过；未读取账号，本次未进入关卡。',mode='done',scene=classify(frame),wins=0,total_completed=len(r.s['completed']))
        return
    if not settings['observe']:r.start_current_screen()
    baseline=len(r.s['completed']);pacer=TransitionPacer()
    while True:
        try:
            control.check();frame=capture_fresh(r.capture,control)
            from PIL import Image
            control.preview(Image.fromarray(frame.image[:,:,::-1]))
            if settings['observe']:
                control.status('只读观察；主线原记录保持不变。',mode='observe',scene=classify(frame),wins=0,total_completed=len(r.s['completed']))
                if request.get('once'):return
                control.sleep(2);continue
            scene=classify(frame)
            if pacer.waiting(scene):
                control.status('等待刚才的操作切换界面；不重复点击。',mode='run',scene=scene)
                control.sleep(.45);continue
            before=getattr(r,'input_sequence',0)
            keep,delay=r.step(frame)
            acted=getattr(r,'input_sequence',0)!=before
            if acted:pacer.applied(scene,entry=bool(r.s.get('active') and scene=='team'))
            if settings.get('fast_mode',True):delay=next_delay(scene,delay,acted)
            wins=len(r.s['completed'])-baseline
            control.status(r.s.get('reason','主线运行中'),mode='run' if keep else 'blocked',scene=classify(frame),wins=wins,total_completed=len(r.s['completed']),stage=(r.s.get('active') or r.ticket or {}).get('key',''),warning=getattr(r,'report_warning',''))
            if not keep:return
            if wins>=int(settings['limit']):control.status('已达到本次主线关数上限，未进入下一关。',mode='done',wins=wins);return
            control.sleep(delay)
        except TaskAttention as exc:
            control.attention(exc);r.ticket=None;pacer.reset();r.s.pop('attention',None);r.save()
        except PauseRun:control.paused();r.ticket=None;pacer.reset()


def observe_mainline(request,control):
    """Read-only first use works without creating a mainline history."""
    from assistant_transport import UnifiedTransport
    from rapidocr_onnxruntime import RapidOCR
    from runner import Frame,classify
    import numpy as np,cv2
    transport=UnifiedTransport(request['settings'],request['target'],control.check)
    ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
    while True:
        try:
            control.check();snap=capture_fresh(transport.capture,control);raw=np.array(snap.image)[:,:,::-1].copy()
            raw=cv2.resize(raw,(1600,900));results,_=ocr(raw)
            control.preview(snap.image)
            control.status('只读观察，不发送输入、不创建或修改通关记录。',mode='observe',scene=classify(Frame(raw,results)))
            if request.get('once'):return
            control.sleep(2)
        except PauseRun:control.paused()


def prepare_selected_profile(request,control):
    """No account OCR/menu navigation. Register first use only after a verified game frame."""
    settings=request['settings']
    if settings.get('data_dir'):
        from assistant_config import history_gate
        root,_=history_gate(settings)
        return root
    if not request.get('user_selected_profile'):raise RuntimeError('缺少开始指令；请重新打开新版界面。')
    from assistant_config import HOME
    from assistant_portable import registered_root,initialize_selected
    from runtime_paths import exclusive_profile
    from assistant_transport import UnifiedTransport
    from rapidocr_onnxruntime import RapidOCR
    import cv2,numpy as np
    from runner import Frame,classify
    with exclusive_profile(HOME):
        if registered_root() is not None:raise RuntimeError('已存在登记；重新打开软件读取原进度，不新建空记录。')
        transport=UnifiedTransport(settings,request['target'],control.check)
        control.status('正在读取当前游戏画面；不读取账号、不打开设置。',mode='checking')
        snap=capture_fresh(transport.capture,control);control.preview(snap.image)
        raw=cv2.resize(np.array(snap.image)[:,:,::-1].copy(),(1600,900))
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2);results,_=ocr(raw)
        scene=classify(Frame(raw,results))
        if scene not in ('map','lobby'):raise RuntimeError('首次使用请停在大厅或主线地图；没有创建进度或发送点击。')
        transport.ensure();control.check()
        root,_=initialize_selected(True)
        settings.update(data_dir=str(root),portable_first_use=False)
        print(json.dumps({'kind':'profile','run_id':request['run_id'],'data_dir':str(root)},ensure_ascii=False),flush=True)
        return root


def acknowledge_previous_stop(root,request,control):
    if request['settings'].get('observe'):return
    marker=Path(root)/'STOP'
    if not marker.exists():return
    if not request.get('user_selected_profile'):raise StopRun()
    stamp=marker.stat().st_mtime
    if not request.get('requested_at') or stamp>request['requested_at']:raise StopRun()
    control.check()
    # The explicit new Start consumes only the previous stop. Any new STOP still vetoes.
    archive=Path(root)/('STOP.previous-'+request['run_id'])
    if archive.exists():raise RuntimeError('停止标记归档已存在；没有覆盖原记录。')
    marker.rename(archive)
    control.log('新开始已归档上次停止标记；历史和新停止指令保留。')

def run_request(request):
    control=Control(request)
    try:
        root,_=validate_run(request['settings'],request['target'],allow_reconcile=True)
        from runtime_paths import exclusive_profile
        if request['settings']['observe']:
            # Independent observer never authorizes account navigation or writes state.
            root.mkdir(parents=True,exist_ok=True)
        else:
            while True:
                try:
                    root=prepare_selected_profile(request,control);break
                except PauseRun:control.paused()
            validate_run(request['settings'],request['target'],allow_reconcile=True)
        with exclusive_profile(root):
            acknowledge_previous_stop(root,request,control)
            while True:
                try:
                    if request['settings']['task']=='abyss':abyss_run(request,control)
                    elif request['settings']['observe']:observe_mainline(request,control)
                    else:mainline_run(request,control)
                    break
                except PauseRun:control.paused()
        if control.last.get('mode') in ('starting','observe'):control.status('只读检查完成；未发送输入。',mode='done')
    except StopRun:control.status('已停止；没有关闭游戏或清除历史。',mode='stopped')
    except Exception as exc:
        control.status(str(exc),mode='blocked')
        control.log('安全停止：'+str(exc))
        with (control.folder/'diagnostic.log').open('a',encoding='utf-8') as f:f.write(traceback.format_exc()+'\n')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--request',type=Path);ap.add_argument('--discover',type=Path)
    args=ap.parse_args()
    if args.discover:
        settings=read_json(args.discover);targets=discover(settings)
        print(json.dumps({'targets':targets,'mumu':settings.get('mumu',{})},ensure_ascii=False));return
    if not args.request:raise RuntimeError('A private request file is required')
    run_request(read_json(args.request))

if __name__=='__main__':main()
