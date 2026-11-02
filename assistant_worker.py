"""One private worker for mainline/Abyss on MuMu/PC. No GUI, no supervisor retries."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, time, traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from assistant_config import CODE_ROOT,atomic_json,read_json,validate_run,reserve_abyss_entry

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
        self.last.update(values)
        if status is not None:self.last['status']=status
        self.last.update(elapsed=int(time.monotonic()-self.started),updated_at=time.time(),run_id=self.run_id)
        atomic_json(self.folder/'status.json',self.last)
        print(json.dumps(dict(kind='status',**self.last),ensure_ascii=False),flush=True)
    def log(self,text):
        print(json.dumps({'kind':'log','text':text},ensure_ascii=False),flush=True)
    def preview(self,image):
        p=self.folder/'preview.tmp.png';image.save(p);os.replace(p,self.folder/'preview.png')
    def sleep(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.check();time.sleep(min(.2,max(0,end-time.monotonic())))
    def paused(self):
        self.status('已暂停；继续时重新截图，不重用旧坐标。',mode='paused')
        while True:
            try:self.check();self.status('继续运行',mode='run');return
            except PauseRun:time.sleep(.2)

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


def discover(settings):
    from pc_backend import Win32Api
    api=Win32Api();targets=[]
    for title in ('第七史诗','第七史詩','Epic Seven'):
        for s in api.windows('',title):
            targets.append(dict(client='pc',hwnd=s.hwnd,pid=s.pid,created=s.created,exe=s.exe,title=title,label=f'桌面端 · PID {s.pid} · {s.width}×{s.height}'))
    cfg=settings.get('mumu',{});adb=Path(cfg.get('adb',''))
    if adb.is_file():
        out=subprocess.run([str(adb),'devices'],capture_output=True,timeout=12,creationflags=subprocess.CREATE_NO_WINDOW)
        for line in out.stdout.decode('utf-8',errors='replace').splitlines()[1:]:
            parts=line.split()
            if len(parts)<2 or parts[1]!='device' or parts[0]!=cfg.get('serial'):continue
            targets.append(dict(client='mumu',serial=parts[0],package=cfg.get('package','com.stove.epic7.google'),label='MuMu · '+parts[0]+' · ADB后台'))
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
    bank=TemplateBank(CODE_ROOT/'.local/assistant/abyss-assets')
    if not bank.entries and not settings['observe']:raise RuntimeError('缺少本机深渊识别模板，已停止；不会盲点或下载素材。')
    session=Session(limit=int(settings['limit']))
    history_path=Path(request['home'])/'abyss-history.json'
    history=read_json(history_path,{'schema':1,'clients':{}})
    label=target['exe'] if target['client']=='pc' else target['serial']+'|'+target['package']
    key=hashlib.sha256((target['client']+'|'+label).encode()).hexdigest()[:24]
    ledger=history.setdefault('clients',{}).setdefault(key,{'attempted':{},'completed':{}})
    previous=None;stable=0;cooldown=0;unknown=None
    while True:
        try:
            control.check();snap=transport.capture();image=snap.image
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
            if reading.scene in (Scene.HARD,Scene.DEFEAT,Scene.BLOCKED):session.plan(reading,obs)
            if reading.scene==Scene.UNKNOWN:
                if session.phase in ('battle_opening','battle') and session.battle_started_at:
                    control.status('等待原生自动战斗或过场；不点击技能。');control.sleep(1);continue
                unknown=unknown or time.monotonic()
                if time.monotonic()-unknown>15:raise PauseRequired('界面连续15秒无法确认，不猜测按钮。')
                control.sleep(1);continue
            unknown=None
            if stable<2 or time.monotonic()<cooldown:control.sleep(.6);continue
            if reading.scene==Scene.CLEAR and reading.floor is not None:
                ledger['completed'].setdefault(str(reading.floor),{'observed_clear_at':time.time()})
                atomic_json(history_path,history)
            if reading.scene==Scene.NORMAL and reading.available_floor is not None:
                floor=str(reading.available_floor)
                if floor in ledger['attempted'] and floor not in ledger['completed']:
                    raise PauseRequired('该层已有未核实的入场意图；不重复消耗体力。')
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
                session.applied(action);control.log('执行：'+action.name);cooldown=time.monotonic()+2;stable=0
            control.sleep(.6)
        except RunComplete as exc:
            if session.last_won_floor is not None:
                ledger['completed'].setdefault(str(session.last_won_floor),{'verified_clear_at':time.time()});atomic_json(history_path,history)
            control.status(str(exc),mode='done',wins=session.wins,scene=Scene.CLEAR.value);return
        except PauseRun:control.paused();previous=None;stable=0


def mainline_run(request,control):
    settings,target=request['settings'],request['target']
    root,state=validate_run(settings,target)
    cfg=read_json(root/'config.json',{})
    cfg.update(max_battle_seconds=cfg.get('max_battle_seconds',1800))
    if target['client']=='mumu':
        cfg.update(settings['mumu']);cfg.update(backend='mumu_adb',serial=target['serial'],package=target['package'])
    else:
        binding=state.get('pc_profile_binding',{})
        cfg.update(backend='stove_pc',pc=dict(game_exe=target['exe'],window_title=target['title'],experimental_input_enabled=True,allow_stretched_client=False,server=binding.get('server',''),account_id=binding.get('account_id','')))
    config_file=Path(request['run_dir'])/'runtime-config.json';atomic_json(config_file,cfg)
    os.environ.update(EPIC7_DATA_DIR=str(root),EPIC7_CONFIG_PATH=str(config_file))
    from runner import Runner,classify
    class ControlledRunner(Runner):
        def ensure_game(self):control.check();return super().ensure_game()
        def adb(self,*args,**kwargs):control.check();return super().adb(*args,**kwargs)
    r=ControlledRunner(observe=True)
    if target['client']=='pc':
        from pc_backend import PcBackend,Win32Api
        if settings['pc_input']=='messages':
            from pc_message_backend import MessageWin32Api
            api=MessageWin32Api()
        else:api=Win32Api()
        api=GuardedApi(api,control)
        if settings['observe']:r.pc=PcBackend(cfg['pc'],root/'STOP',api=api,read_only=True)
        else:
            if not cfg['pc']['server'] or not cfg['pc']['account_id']:raise RuntimeError('原主线记录尚无可核实的桌面账号绑定；保留历史，拒绝空记录启动。')
            from pc_quickstart import inspect_account,capture_frame,return_to_game,same_account
            from rapidocr_onnxruntime import RapidOCR
            backend=PcBackend(cfg['pc'],root/'STOP',api=api)
            ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
            capture=lambda:capture_frame(backend,ocr,Path(request['run_dir'])/'preflight')
            control.status('自动核对当前已登录账号；不切服、不处理认证。',mode='run')
            proof=inspect_account(backend,capture)
            if not same_account(proof,state['pc_profile_binding']):raise RuntimeError('当前账号与原主线历史不一致，未换绑。')
            backend.authorize(proof);return_to_game(backend,capture);r.pc=backend
    baseline=len(r.s['completed']);deadline=None
    while True:
        try:
            control.check();frame=r.capture()
            from PIL import Image
            control.preview(Image.fromarray(frame.image[:,:,::-1]))
            if settings['observe']:
                control.status('只读观察；主线原记录保持不变。',mode='observe',scene=classify(frame),wins=0,total_completed=len(r.s['completed']))
                if request.get('once'):return
                control.sleep(2);continue
            keep,delay=r.step(frame)
            wins=len(r.s['completed'])-baseline
            control.status(r.s.get('reason','主线运行中'),mode='run' if keep else 'blocked',scene=classify(frame),wins=wins,total_completed=len(r.s['completed']),stage=(r.s.get('active') or r.ticket or {}).get('key',''))
            if not keep:return
            if wins>=int(settings['limit']):control.status('已达到本次主线关数上限，未进入下一关。',mode='done',wins=wins);return
            control.sleep(delay)
        except PauseRun:control.paused()


def run_request(request):
    control=Control(request)
    try:
        root,_=validate_run(request['settings'],request['target'])
        from runtime_paths import exclusive_profile
        with exclusive_profile(root):
            while True:
                try:
                    if request['settings']['task']=='abyss':abyss_run(request,control)
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
        print(json.dumps({'targets':discover(read_json(args.discover))},ensure_ascii=False));return
    if not args.request:raise RuntimeError('A private request file is required')
    run_request(read_json(args.request))

if __name__=='__main__':main()
