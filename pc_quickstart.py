"""旧版桌面端启动工具：使用已登录游戏并保留原进度。

统一界面为推荐入口；此旧版工具仍会核验账号，仅供历史维护。
导入此模块不会发送游戏输入。桌面端适配仍为实验性。
"""
from __future__ import annotations
import copy,hashlib,json,os,subprocess,sys,time
from contextlib import ExitStack
from pathlib import Path
CODE_ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(CODE_ROOT));sys.path.insert(0,str(CODE_ROOT/'vendor'))
from ui_text import ChineseArgumentParser,error_text


def load_preferences(home):
    path=home/'preferences.json'
    if not path.exists():return {}
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict):raise RuntimeError('本机启动记录损坏，停止；不会创建空进度替代')
    return value


def existing_profile(home,prefs,code_root=CODE_ROOT):
    """Never silently replace a missing, stopped or unbound history."""
    value=prefs.get('data_dir')
    if value:
        root=Path(value).expanduser()
        if not root.is_absolute() or not (root/'state.json').is_file():
            raise RuntimeError('原进度目录不存在；停止，不创建空进度绕过历史')
        return root.resolve()
    legacy=code_root/'config.pc.local.json'
    if legacy.exists():
        cfg=json.loads(legacy.read_text(encoding='utf-8-sig'))
        value=cfg.get('data_dir')
        if not value or not Path(value).is_absolute() or not (Path(value)/'state.json').is_file():
            raise RuntimeError('旧配置的进度目录无效；不会跳过旧历史')
        return Path(value).resolve()
    if (code_root/'state.json').exists():return code_root.resolve()
    profiles=home/'profiles'
    dirs=list(profiles.iterdir()) if profiles.exists() else []
    if len(dirs)>1 or any(not d.is_dir() or not (d/'state.json').is_file() for d in dirs):
        raise RuntimeError('发现多份或不完整的本机进度；请先明确进度归属，不自动新建')
    return dirs[0].resolve() if dirs else None


def read_state(root):
    s=json.loads((root/'state.json').read_text(encoding='utf-8-sig'))
    if not isinstance(s.get('attempted'),dict) or not isinstance(s.get('completed'),dict):
        raise RuntimeError('进度历史无效；不会清空修复')
    return s


def entry_gate(root,state,resume=False):
    if state.get('active'):
        raise RuntimeError('已有战败/未结算入场记录：'+str(state['active'].get('key',''))+'。不重新入场；手动通过并补记后再继续。')
    if not resume and ((root/'STOP').exists() or state.get('terminal')):
        raise RuntimeError('当前已安全停止。请查看原因，需要继续时使用 PCResume；不会自动移除停止标记。')


def same_account(proof,binding):
    return all(str(proof.get(k,''))==str(binding.get(k,'')) for k in ('server','account_id'))


def select_profile(home,hint,state,proof):
    if hint:
        binding=state.get('pc_profile_binding')
        if binding and not same_account(proof,binding):
            raise RuntimeError('检测到登录账号/服务器与原进度不一致；未切服、未换绑、未创建空历史')
        return hint,state
    digest=hashlib.sha256((proof['server']+'\0'+proof['account_id']).encode()).hexdigest()[:24]
    root=home/'profiles'/digest
    if root.exists():raise RuntimeError('该角色原进度目录已存在但未成功读取；停止，不覆盖')
    # Genuine first-time users only. Registered/legacy/missing histories never use this branch.
    from runner import now
    return root,dict(schema=1,started_at=now(),attempted={},completed={},active=None,victories=0,
                     initialization='first_use_verified_account',pc_profile_binding=dict(server=proof['server'],account_id=proof['account_id'],bound_at=now()))


def capture_frame(backend,ocr,private):
    import cv2
    from runner import Frame,atomic_json,now
    raw=backend.capture();h,w=raw.shape[:2];image=cv2.resize(raw,(1600,900))
    results,_=ocr(image);frame=Frame(image,results,(w,h))
    private.mkdir(parents=True,exist_ok=True)
    (private/'latest.png').write_bytes(cv2.imencode('.png',image)[1].tobytes())
    atomic_json(private/'latest-ocr.json',dict(time=now(),words=frame.words,text=frame.text))
    return frame


def inspect_account(backend,capture):
    """Finite navigation, at most one click per recognized navigation screen."""
    from pc_startup import observed_account,StartupBlocked
    from runner import resource_warning
    seen=set()
    for _ in range(5):
        frame=capture()
        try:proof=observed_account(frame,backend.window)
        except StartupBlocked:
            # Do not navigate from a partly readable account page.
            if frame.find('服务器账号编号',(100,480,650,640)):
                raise RuntimeError('账号字段不可读；没有猜测或选择服务器')
            from pc_startup import navigation_target
            kind,_=navigation_target(frame)
            if kind in seen:raise RuntimeError('启动导航画面未改变；不重复点击，保留现场')
            seen.add(kind);backend.navigate_account(frame);time.sleep(.6)
            continue
        confirm=capture();second=observed_account(confirm,backend.window)
        if not same_account(proof,second) or proof['window']!=second['window']:
            raise RuntimeError('连续两帧账号核对不一致，停止')
        if resource_warning(confirm):raise RuntimeError('资源弹窗优先，停止')
        return second,confirm
    raise RuntimeError('自动账号读取未完成；没有发起关卡入场')


def return_to_game(backend,capture):
    from runner import classify,resource_warning
    for _ in range(2):
        backend.back();time.sleep(.6);frame=capture()
        if resource_warning(frame):raise RuntimeError('返回游戏遇到资源提示，停止')
        if classify(frame) in ('map','lobby'):return frame
        if not frame.find(r'^(设置|设定)$',(0,0,500,160)):
            raise RuntimeError('返回游戏后画面不明；不继续按返回或点击')
    raise RuntimeError('未返回地图/大厅，不启动关卡状态机')


def start_supervisor(cfg,root,state,proof,private,release):
    from runner import atomic_json,now
    runtime=private/'runtime-config.json'
    cfg['pc_preflight']=proof;atomic_json(runtime,cfg)
    new=copy.deepcopy(state)
    new.setdefault('pc_profile_binding',dict(server=proof['server'],account_id=proof['account_id'],bound_at=now()))
    new.update(terminal=False,status='PC一键启动核验完成',reason='使用当前已登录角色；服务器/账号自动读取，复用原进度',updated_at=now())
    atomic_json(root/'state.json',new)
    env=os.environ.copy();env.update(EPIC7_DATA_DIR=str(root),EPIC7_CONFIG_PATH=str(runtime),PYTHONIOENCODING='utf-8')
    release()
    with (root/'pc-launcher.log').open('a',encoding='utf8') as out:
        child=subprocess.Popen([sys.executable,'-B','-X','utf8',str(CODE_ROOT/'supervisor.py')],cwd=str(root),env=env,stdout=out,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    print('已请求启动，进程编号：',child.pid,'；实际战斗状态请看运行记录，不能把启动请求当成已开战。')


def main(argv=None):
    ap=ChineseArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['start','resume','check','stop'],nargs='?',default='start')
    ap.add_argument('--delay',type=int,default=7)
    args=ap.parse_args(argv)
    if not 2<=args.delay<=60:raise RuntimeError('等待时间需为2至60秒')
    home=CODE_ROOT/'.local'/'pc';home.mkdir(parents=True,exist_ok=True)
    prefs=load_preferences(home);hint=existing_profile(home,prefs)
    state=read_state(hint) if hint else None
    if args.command=='stop':
        if not hint:raise RuntimeError('尚无本机运行进度，不需要停止')
        (hint/'STOP').write_text('桌面端用户请求停止',encoding='utf8');print('已请求停止脚本，不关闭游戏。');return
    if args.command!='check' and hint:entry_gate(hint,state,args.command=='resume')
    from runtime_paths import exclusive_profile
    from pc_backend import PcBackend,Win32Api
    from rapidocr_onnxruntime import RapidOCR
    from runner import atomic_json,now
    with ExitStack() as stack:
        launch_lock=home/'launcher';launch_lock.mkdir(exist_ok=True)
        release_global=stack.enter_context(exclusive_profile(launch_lock))
        release_profile=stack.enter_context(exclusive_profile(hint)) if hint else lambda:None
        if hint and read_state(hint)!=state:raise RuntimeError('进度已被其他写入者更改，停止')
        # STOP is only removed by a separate, explicit Resume entry.
        old_stop=None;started=False
        if args.command=='resume' and hint:
            if input('仅恢复安全暂停，不会重打失败关。确认继续请输入“继续”：').strip().upper() not in ('继续','Y'):return
            stop=hint/'STOP'
            if stop.exists():old_stop=stop.read_bytes();stop.unlink()
        try:
            print(f'请在{args.delay}秒内将已登录的游戏地图或大厅前置。无需选服务器、填账号或手动打开设置。',flush=True)
            time.sleep(args.delay)
            api=Win32Api();windows=api.windows(None,'第七史诗')
            if len(windows)!=1:raise RuntimeError('需要且只能有一个已打开的第七史诗游戏窗口')
            pc=dict(game_exe=windows[0].exe,window_title='第七史诗',allow_stretched_client=False,experimental_input_enabled=True)
            stop_path=(hint if hint else home/'launcher')/'STOP'
            private=home/'check';private.mkdir(parents=True,exist_ok=True)
            b=PcBackend(pc,stop_path,api=api,read_only=args.command=='check');b.window=windows[0]
            ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
            capture=lambda:capture_frame(b,ocr,private)
            if args.command=='check':
                capture();print('只读检查完成：发现游戏窗口，截图已保存；没有点击、按键、入场或修改历史。');return
            # A first-use consent covers navigation only; task input still needs fresh account proof.
            first=not prefs.get('experimental_consent') or not state or not state.get('pc_profile_binding')
            if first:
                print('首次使用：PC版仍是实验性。仅正常体力，不购买、不复活、不重打。')
                print('将自动读取当前已登录账号并绑定原进度；有旧历史时不会新建替代。')
                if hint:print('已有进度：',hint,'；通关数：',len(state['completed']),'；最近通关：',(state.get('last_cleared') or {}).get('key','无'))
                if hint:print('已有进度：',hint,'；通关数：',len(state['completed']),'；最近通关：',(state.get('last_cleared') or {}).get('key','无'))
                if input('确认使用当前登录角色及这份历史请输入“确认”（以后正常启动不再询问）：').strip().upper() not in ('确认','Y'):return
                # Console consent steals focus; give time to restore the game.
                print(f'请在{args.delay}秒内把游戏前置。',flush=True);time.sleep(args.delay)
            proof,frame=inspect_account(b,capture)
            if prefs.get('expected_server') and proof['server']!=prefs['expected_server']:
                raise RuntimeError('登录服务器与迁移进度不一致；不切服、不创建新历史')
            root,selected=select_profile(home,hint,state,proof)
            if not hint:
                root.mkdir(parents=True,exist_ok=False)
                release_profile=stack.enter_context(exclusive_profile(root))
                atomic_json(root/'state.json',selected)
            else:
                if read_state(root)!=state:raise RuntimeError('账号核对期间进度改变，停止')
            # Discover values internally: no account/server/exe JSON to maintain.
            pc.update(server=proof['server'],account_id=proof['account_id'])
            b.stop_path=root/'STOP';b.authorize(proof)
            return_to_game(b,capture)
            if b.stop_path.exists():raise RuntimeError('用户停止标记优先，不启动')
            if read_state(root)!=selected:raise RuntimeError('启动前历史变化，停止')
            prefs.update(data_dir=str(root),experimental_consent=True)
            atomic_json(home/'preferences.json',prefs)
            atomic_json(private/'preflight.json',proof)
            cfg=dict(backend='stove_pc',data_dir=str(root),max_battle_seconds=1800,pc=pc)
            def release():release_profile();release_global()
            start_supervisor(cfg,root,selected,proof,private,release);started=True
        finally:
            if old_stop is not None and not started and hint and not (hint/'STOP').exists():
                (hint/'STOP').write_bytes(old_stop)


if __name__=='__main__':
    try:main()
    except Exception as e:print('桌面端安全停止：'+error_text(e),file=sys.stderr);raise SystemExit(1)
