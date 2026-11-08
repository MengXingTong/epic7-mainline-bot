"""Run-bound controls; new starts use the GUI; audited same-run reloads never reset quotas."""
import sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ui_text import ACTION_NAMES,ChineseArgumentParser
from assistant_config import HOME,read_json,atomic_json

def restore_arena_after_busy_start(home,source_run_id,current_run_id):
    """Repair one proven GUI-start/maintenance collision; no new quota/input.

    The newer request must have failed before obtaining its target lease and
    must own zero game records. Only the unique incumbent's saved maintenance
    receipt, overlapping that failed Start, can restore its existing batch.
    """
    import hashlib,time
    from assistant_config import process_is_alive,validate_run
    home=Path(home).resolve();marker_path=home/'active-run.json';marker=read_json(marker_path,{})
    if marker.get('run_id')!=current_run_id or source_run_id==current_run_id:
        raise ValueError('当前失败任务已变化；不关联旧批次。')
    source_folder=(home/'runs'/source_run_id).resolve();current_folder=(home/'runs'/current_run_id).resolve()
    if source_folder.parent!=(home/'runs').resolve() or current_folder.parent!=(home/'runs').resolve():
        raise ValueError('来源不在原助手任务目录内。')
    source=read_json(source_folder/'request.json');current=read_json(current_folder/'request.json')
    status=read_json(current_folder/'status.json');old_status=read_json(source_folder/'status.json')
    if (Path(marker.get('run_dir','')).resolve()!=current_folder
        or source.get('run_id')!=source_run_id or current.get('run_id')!=current_run_id
        or any(Path(r.get('home','')).resolve()!=home for r in (source,current))
        or source.get('target')!=current.get('target')
        or any(r.get('settings',{}).get('task')!='arena' for r in (source,current))
        or source['settings'].get('arena_count')!=current['settings'].get('arena_count')
        or Path(source['settings'].get('data_dir','')).resolve()!=Path(current['settings'].get('data_dir','')).resolve()
        or status.get('run_id')!=current_run_id or status.get('mode')!='blocked'
        or status.get('status')!='该游戏窗口/模拟器已由另一个助手控制；请选择其他客户端实例。'
        or status.get('wins')!=0 or status.get('scene')!='—'
        or old_status.get('run_id')!=source_run_id or old_status.get('mode')!='stopped'
        or process_is_alive(marker.get('worker_pid'))):
        raise ValueError('不是同目标/原次数、零输入的维护碰撞；不恢复或新开。')
    root,_=validate_run(source['settings'],source['target'],allow_reconcile=True)
    from arena_journal import ArenaJournal
    state=read_json(root/'arena/state.json')
    if (source_run_id not in state.get('runs',{}) or current_run_id in state.get('runs',{})
        or any(a.get('run_id')==current_run_id for a in state.get('actions',[]))
        or any(a.get('run_id')==current_run_id for a in state.get('attempted',{}).values())
        or (root/'STOP').exists()):raise ValueError('碰撞请求已有游戏记录或STOP；不换回原批次。')
    j=ArenaJournal(root,source_run_id,source['settings']['arena_count'],persist=False)
    if j.active or any(r.get('pending_result') for r in state['runs'].values()) or any(k not in state['completed'] for k in state['attempted']):
        raise ValueError('存在未结算资源入场；不由启动碰撞恢复。')
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    request_hash=digest(source_folder/'request.json');candidates=[]
    for path in source_folder.glob('arena-local-reload-*.json'):
        report=read_json(path)
        if (report.get('run_id')==source_run_id and report.get('phase')=='finished'
            and report.get('at',0)<current.get('requested_at',0)<report.get('finished_at',0)
            and report.get('final_status')==old_status
            and report.get('source_files',{}).get(str(source_folder/'request.json'))==request_hash
            and report.get('active_marker',{}).get('run_id')==source_run_id):candidates.append((path,report))
    if len(candidates)!=1:raise ValueError('没有唯一且时间重叠的原维护来源；不猜测批次。')
    path,report=candidates[0];restored=report['active_marker']
    if Path(restored.get('run_dir','')).resolve()!=source_folder or process_is_alive(restored.get('worker_pid')):
        raise ValueError('原维护进程仍在运行或路径不符；不恢复第二个执行者。')
    files=[marker_path,root/'arena/state.json',path]
    files += [folder/name for folder in (source_folder,current_folder) for name in ('request.json','status.json','control.json')]
    hashes={str(p):digest(p) for p in files};nonce=uuid.uuid4().hex
    receipt=source_folder/('arena-busy-start-restore-'+nonce+'.json')
    atomic_json(receipt,dict(phase='verified',source_run_id=source_run_id,current_run_id=current_run_id,
        source_files=hashes,old_marker=marker,restored_marker=restored,
        original_control=read_json(source_folder/'control.json'),at=time.time(),game_input_sent=False,quota_reset=False))
    if read_json(marker_path,{})!=marker or any(digest(Path(p))!=h for p,h in hashes.items()):
        raise ValueError('碰撞恢复来源在落盘期间变化；未激活。')
    # A real stop command for an already exited source, not a forged stopped
    # status. The standard loader will still validate it and acquire all leases.
    atomic_json(source_folder/'control.json',dict(run_id=source_run_id,action='stop',command_id=nonce))
    if read_json(marker_path,{})!=marker:raise ValueError('新的启动已到达；不覆盖当前关联。')
    atomic_json(marker_path,restored)
    return receipt


def reload_original_arena(home,expected_run_id):
    """Explicit local maintenance, not Start/restart and not a quota retry.

    Uses the existing stopped-original-run loader. The worker retains the exact
    request/run/quota and all dispatches; game/profile/target leases are still
    acquired by run_request. No assistant window or desktop input is involved.
    """
    import contextlib,hashlib,os,time
    from assistant_instances import NamedLeases
    from assistant_config import load_theater_resume_request,process_is_alive,validate_run
    from assistant_worker import run_request
    home=Path(home).resolve();marker_path=home/'active-run.json'
    marker=read_json(marker_path,{})
    if marker.get('run_id')!=expected_run_id:raise ValueError('当前任务已变化；不重载旧任务。')
    api=NamedLeases();lease=api.acquire(r'Local\Epic7Assistant.ArenaReload.'+hashlib.sha256(str(home).casefold().encode()).hexdigest())
    if lease is None:raise ValueError('已有同run维护重载；不启动第二个执行者。')
    try:
        folder=Path(marker['run_dir']).resolve()
        source=read_json(folder/'request.json',{})
        if source.get('settings',{}).get('task')!='arena':raise ValueError('此通道仅重载原竞技场run，不改选任务。')
        request=load_theater_resume_request(expected_run_id,home)
        root,_=validate_run(request['settings'],request['target'],allow_reconcile=True)
        files=[folder/name for name in ('request.json','status.json','control.json')]+[root/'arena/state.json']
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
        hashes={str(p):digest(p) for p in files}
        if read_json(marker_path,{})!=marker or process_is_alive(marker.get('worker_pid')):
            raise ValueError('原工作进程/当前任务已变化；不激活维护执行者。')
        nonce=uuid.uuid4().hex;receipt=folder/('arena-local-reload-'+nonce+'.json')
        registered=dict(run_id=expected_run_id,run_dir=str(folder),worker_pid=os.getpid())
        report=dict(run_id=expected_run_id,phase='reserved',at=time.time(),source_files=hashes,
            original_marker=marker,active_marker=registered,quota_reset=False,request_replaced=False)
        atomic_json(receipt,report)
        if (read_json(marker_path,{})!=marker or any(digest(Path(p))!=h for p,h in hashes.items())
            or (root/'STOP').exists()):raise ValueError('维护激活前来源/停止状态已变化；没有继续输入。')
        # Register before allowing input; Control.check revokes us if this exact
        # marker is later replaced. All ordinary pause/stop commands still apply.
        atomic_json(marker_path,registered)
        if digest(folder/'control.json')!=hashes[str(folder/'control.json')]:
            raise ValueError('新的停止/控制命令已到达；不覆盖。')
        atomic_json(folder/'control.json',dict(run_id=expected_run_id,action='run',command_id=nonce))
        effective=dict(request,arena_maintenance=dict(active_marker=registered,receipt=str(receipt)))
        class Tee:
            def __init__(self,output,log):self.output=output;self.log=log
            def write(self,value):self.log.write(value);self.log.flush();return self.output.write(value)
            def flush(self):self.log.flush();self.output.flush()
        print('按原run加载新代码；保留原次数和全部记录，不新开批次，不操作助手窗口。',flush=True)
        try:
            with (folder/'worker.log').open('a',encoding='utf-8') as log:
                with contextlib.redirect_stdout(Tee(sys.stdout,log)):run_request(effective)
        finally:
            report.update(phase='finished',finished_at=time.time(),final_status=read_json(folder/'status.json',{}),ending_marker=read_json(marker_path,{}))
            atomic_json(receipt,report)
    finally:api.release(lease)


def main():
    ap=ChineseArgumentParser();ap.add_argument('--instance',type=int);ap.add_argument('action',choices=('stop','pause','resume','restart','status','reload-arena'));ap.add_argument('--task',choices=('mainline','abyss','saint_3_7','dimension','theater','arena'));a=ap.parse_args()
    from assistant_instances import slot_home,homes,worker_alive
    home=slot_home(HOME,a.instance) if a.instance is not None else HOME
    if a.instance is None and any(worker_alive(path) for number,path in homes(HOME) if number!=1):
        raise ValueError('存在其他助手实例；请用 --instance 编号明确指定，避免控制错误任务。')
    active=read_json(home/'active-run.json',{})
    if not active:print('当前没有运行中的统一助手工作进程。');return
    folder=Path(active['run_dir']).resolve()
    if folder.parent!=(home/'runs').resolve():raise ValueError('任务目录不在受管理的工作区内。')
    status=read_json(folder/'status.json',{})
    if status.get('run_id')!=active['run_id']:raise ValueError('工作进程身份不匹配，已拒绝操作。')
    if a.action=='status':
        import json
        print(json.dumps(status,ensure_ascii=False,indent=2));return
    if a.action=='reload-arena':
        if a.task not in (None,'arena'):raise ValueError('原run重载不能改选任务。')
        reload_original_arena(home,active['run_id']);return
    if a.action=='restart':
        request=read_json(folder/'request.json',{})
        if (a.task or request.get('settings',{}).get('task')) in ('penguin','arena'):
            raise ValueError('指定数量/次数的任务不能通过维护重启重复旧目标；请在界面确认本次目标后明确开始。')
        atomic_json(home/'gui-command.json',{'command_id':uuid.uuid4().hex,'action':'restart','expected_run_id':active['run_id'],'task':a.task or request.get('settings',{}).get('task','mainline')})
        print('已通过现有界面请求安全重启工作进程；未重置历史或重启游戏。');return
    if a.action=='resume' and status.get('mode') not in ('paused','attention'):raise ValueError('只有已暂停或等待处理的工作进程才能继续；未执行重启。')
    atomic_json(folder/'control.json',{'run_id':active['run_id'],'action':'run' if a.action=='resume' else a.action,'command_id':uuid.uuid4().hex})
    print('已请求'+ACTION_NAMES[a.action]+'；游戏和历史记录保持不变。')

if __name__=='__main__':main()
