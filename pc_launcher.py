"""旧版实验性桌面端启动器；不自动登录、选择服务器或创建空进度。"""
from __future__ import annotations
import json,os,subprocess,sys,time
from pathlib import Path
CODE_ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(CODE_ROOT));sys.path.insert(0,str(CODE_ROOT/'vendor'))
from ui_text import ChineseArgumentParser,error_text
from pc_clients import pc_distribution

def load_settings(path):
    cfg=json.loads(path.read_text(encoding='utf-8-sig'))
    if cfg.get('backend')!='stove_pc':raise RuntimeError('旧版桌面端配置必须明确选择 stove_pc 后端。')
    pc=cfg.get('pc',{})
    if not Path(pc.get('game_exe','')).is_absolute() or pc_distribution(pc['game_exe']) is None:
        raise RuntimeError('请配置本机游戏进程 EpicSeven.exe（STOVE）或 EpicSeven_Steam.exe（Steam）的准确路径。')
    if not pc.get('server') or not str(pc.get('account_id','')).isdigit():raise RuntimeError('旧版启动流程需要服务器和纯数字服务器账号编号。')
    if not cfg.get('data_dir') or not Path(cfg['data_dir']).is_absolute():raise RuntimeError('请明确选择已有账号进度目录；不会创建空记录。')
    pc['account_id']=str(pc['account_id'])
    root=Path(cfg['data_dir']).resolve()
    state=json.loads((root/'state.json').read_text(encoding='utf8'))
    if not isinstance(state.get('attempted'),dict) or not isinstance(state.get('completed'),dict):raise RuntimeError('所选进度目录的历史记录无效。')
    binding=state.get('pc_profile_binding')
    if binding and any(str(binding.get(k,''))!=str(pc.get(k,'')) for k in ('server','account_id')):
        raise RuntimeError('此历史已绑定其他桌面端账号或服务器；不会自动重新绑定。')
    return cfg,root,state

def wait_for_game(seconds):
    print(f'请在 {seconds} 秒内将正确游戏窗口前置；PC适配不会自动抢焦点。',flush=True)
    time.sleep(seconds)

def read_frame(cfg,root,delay):
    from pc_backend import PcBackend
    import cv2,numpy as np
    from rapidocr_onnxruntime import RapidOCR
    from runner import Frame,atomic_json,now
    wait_for_game(delay)
    backend=PcBackend(cfg['pc'],root/'STOP',read_only=True)
    raw=backend.capture();h,w=raw.shape[:2]
    image=cv2.resize(raw,(1600,900))
    results,_=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)(image)
    frame=Frame(image,results,(w,h))
    private=CODE_ROOT/'.local'/'pc-check';private.mkdir(parents=True,exist_ok=True)
    (private/'latest.png').write_bytes(cv2.imencode('.png',image)[1].tobytes())
    atomic_json(private/'latest-ocr.json',dict(time=now(),words=frame.words,text=frame.text))
    return backend,frame,private

def run(args,cfg,root,state,release=lambda:None):
    if args.command=='stop':
        (root/'STOP').write_text('桌面端用户请求停止',encoding='utf8');print('已请求停止共享账号输入，不关闭游戏。');return
    if args.command in ('start','resume'):
        if state.get('active'):raise RuntimeError('已有未结算/失败入场记录。先手动补过，再 check 和 reconcile；绝不重新入场。')
        if args.command=='start' and (state.get('terminal') or (root/'STOP').exists()):raise RuntimeError('此进度已停止；请检查进度后明确执行续跑命令。')
        if not cfg['pc'].get('experimental_input_enabled',False):raise RuntimeError('桌面端输入仍为实验性且默认禁用；请先阅读桌面端指南，再决定是否在本机启用。')
        phrase='继续' if args.command=='resume' else '开始'
        legacy_phrase='PC RESUME' if args.command=='resume' else 'PC START'
        print('仅使用正常入场体力；不兑换、不复活、不重打。PC原生输入仍需使用者自行完成现场验收。')
        print('数据目录：',root)
        print('目标服务器/账号编号：',cfg['pc']['server'],cfg['pc']['account_id'])
        print('历史通关数：',len(state.get('completed',{})),'；最近通关：',(state.get('last_cleared') or {}).get('key','无'))
        print('首次确认会把该历史绑定到上述账号/服务器；请确认它们确实属于同一角色。')
        if input(f'明确确认请输入 {phrase}：').strip() not in (phrase,legacy_phrase):print('已取消。');return
    backend,frame,private=read_frame(cfg,root,args.delay)
    from pc_profile import account_preflight
    from runner import atomic_json,now,classify
    proof_path=private/'preflight.json'
    if args.command=='reconcile':
        from state_tools import manual_clear
        from runner import Runner
        if not proof_path.is_file():raise RuntimeError('先在账号信息页执行 check，再在120秒内回到原关卡的绿色通关节点执行 reconcile')
        proof=json.loads(proof_path.read_text(encoding='utf8'))
        if time.time()-proof.get('checked_at',0)>120 or proof.get('checked_at',0)>time.time()+5 or proof.get('window')!=backend.window.identity():raise RuntimeError('桌面端账号核验凭据已过期或属于其他窗口。')
        if any(proof.get(k)!=str(cfg['pc'].get(k,'')) for k in ('server','account_id')):raise RuntimeError('桌面端进度配置已变化。')
        if classify(frame)!='map':raise RuntimeError('补记通关需要在地图中精确选中原来已通关的关卡。')
        r=Runner.__new__(Runner);node,_,kind=r.map_ticket(frame)
        # Refresh after OCR, preserving the original geometry comparison.
        if backend.snapshot()!=backend.frame_window:raise RuntimeError('补记通关期间桌面端窗口位置或尺寸发生变化。')
        new=manual_clear(state,node,kind,'evidence/pc-manual-clear-'+str(node.get('key') if node else 'unknown')+'.png',now())
        if input('原入场记录不会清空。确认补记人工通关请输入“已通关”：').strip() not in ('已通关','PC CLEARED'):print('已取消。');return
        # Re-read before any write: another process must not have changed the profile.
        if json.loads((root/'state.json').read_text(encoding='utf8'))!=state:raise RuntimeError('进度已变化；未写入补记记录。')
        import cv2
        path=root/new['last_cleared']['evidence'];path.parent.mkdir(exist_ok=True);path.write_bytes(cv2.imencode('.png',frame.image)[1].tobytes())
        new.update(terminal=True,status='人工补过已核实，等待PC续跑',reason='保留全部原始尝试；未启动或重新入场',updated_at=now())
        atomic_json(root/'state.json',new);print('已补记人工通关，仍保持停止；没有游戏输入。');return
    proof=account_preflight(frame,cfg['pc'],backend.window)
    atomic_json(proof_path,proof)
    print('PC服务器与账号编号精确核验通过；预览只保存在本机 .local/pc-check。')
    if args.command=='check':print('仅检查：未点击、未按键、未进入关卡，也未修改历史。');return
    # A separately constructed input backend is required. The read-only instance
    # cannot be promoted to input mode, even by calling authorize().
    if json.loads((root/'state.json').read_text(encoding='utf8'))!=state:raise RuntimeError('进度已变化；已取消启动。')
    if args.command=='resume' and (root/'STOP').exists():(root/'STOP').unlink()
    from pc_backend import PcBackend
    observed=backend
    backend=PcBackend(cfg['pc'],root/'STOP')
    backend.window=observed.window;backend.frame_window=observed.frame_window;backend.frame_at=observed.frame_at
    backend.authorize(proof)
    backend.back()  # Only leave the exactly verified account-info screen.
    state.setdefault('pc_profile_binding',dict(server=cfg['pc']['server'],account_id=cfg['pc']['account_id'],bound_at=now()))
    state.update(terminal=False,status='PC启动核验完成',reason='使用现有账号记录；等待地图新关校验',updated_at=now())
    atomic_json(root/'state.json',state)
    cfg['pc_preflight']=proof
    runtime=private/'runtime-config.json';atomic_json(runtime,cfg)
    env=os.environ.copy();env['EPIC7_DATA_DIR']=str(root);env['EPIC7_CONFIG_PATH']=str(runtime);env['PYTHONIOENCODING']='utf-8'
    release()  # Let the new supervisor acquire the same profile lock.
    with (root/'pc-launcher.log').open('a',encoding='utf8') as out:
        child=subprocess.Popen([sys.executable,'-B','-X','utf8',str(CODE_ROOT/'supervisor.py')],cwd=str(root),env=env,stdout=out,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    print('已请求桌面端后台启动，进程编号：',child.pid,'；失焦/遮挡/窗口变化将停止输入。')

def main():
    ap=ChineseArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['check','start','resume','reconcile','stop'])
    ap.add_argument('--config',type=Path,default=CODE_ROOT/'config.pc.local.json')
    ap.add_argument('--delay',type=int,default=7)
    args=ap.parse_args()
    if not 2<=args.delay<=60:raise RuntimeError('等待时长必须在 2 到 60 秒之间。')
    cfg,root,state=load_settings(args.config)
    if args.command in ('start','resume','reconcile'):
        from runtime_paths import exclusive_profile
        with exclusive_profile(root) as release:
            if json.loads((root/'state.json').read_text(encoding='utf8'))!=state:raise RuntimeError('获取进度锁前记录已变化，已拒绝操作。')
            return run(args,cfg,root,state,release)
    return run(args,cfg,root,state)

if __name__=='__main__':
    try:main()
    except Exception as e:print('桌面端安全停止：'+error_text(e),file=sys.stderr);raise SystemExit(1)
