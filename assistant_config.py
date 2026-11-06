"""Shared settings/selection policy. No game input and no empty-history migration."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
CODE_ROOT=Path(__file__).resolve().parent
HOME=Path(os.environ.get('EPIC7_ASSISTANT_HOME',str(CODE_ROOT/'.local'/'assistant'))).resolve()


def read_json(path,default=None):
    path=Path(path)
    if not path.exists():return default
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict):raise ValueError('JSON 内容不是有效对象：'+str(path))
    return value


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,path)


def load_settings(home=HOME):
    saved=read_json(Path(home)/'settings.json')
    from assistant_portable import enabled,registered_root
    if enabled():
        result={'client':'auto','task':'mainline','pc_input':'messages','observe':False,'data_dir':'','mumu':{}}
        if saved is not None:result.update(saved)
        root=registered_root(home)
        if root:result['data_dir']=str(root)
        elif result.get('data_dir'):
            root=Path(result['data_dir'])
            if not root.is_absolute():root=CODE_ROOT/root
            if not (root/'state.json').is_file():raise ValueError('原进度丢失；不初始化替代。')
            result['data_dir']=str(root.resolve())
        result.update(observe=False,pc_input='messages',start_policy='current_screen',fast_mode=True)
        result['portable_first_use']=not bool(result.get('data_dir'))
        result['worker_python']=str(CODE_ROOT/'runtime'/'python.exe')
        result.pop('limit',None);return result
    if saved is not None:
        result={**saved,'observe':False,'pc_input':'messages','start_policy':'current_screen','fast_mode':True}
        result.pop('limit',None);return result
    prefs=read_json(CODE_ROOT/'.local/pc/preferences.json',{})
    registered=registered_root(home)
    root=prefs.get('data_dir','') or (str(registered) if registered else '')
    # Existing history is referenced in place, never copied/reset by the GUI.
    result={'client':'auto','task':'mainline','pc_input':'messages','observe':False,
            'data_dir':root,'worker_python':'','mumu':{},'start_policy':'current_screen','fast_mode':True}
    hint=CODE_ROOT/'.local/python-path.txt'
    if hint.exists():result['worker_python']=hint.read_text(encoding='utf-8-sig').strip()
    if root:
        if not (Path(root)/'state.json').is_file():raise ValueError('原主线进度丢失；未创建空记录替代。')
        cfg=read_json(Path(root)/'config.json',{})
        result['mumu']={k:cfg[k] for k in ('adb','serial','package') if k in cfg}
    return result


def select_target(client,targets):
    if client not in ('auto','mumu','pc'):raise ValueError('未知的客户端选项。')
    rows=[t for t in targets if client=='auto' or t['client']==client]
    if len(rows)!=1:raise ValueError('未找到唯一客户端；请选择客户端和具体实例，不自动切换。')
    return rows[0]


def history_gate(settings):
    root=Path(settings.get('data_dir',''))
    if not root.is_absolute() or not (root/'state.json').is_file():raise ValueError('未找到原主线进度，不能新建空记录绕过历史。')
    state=read_json(root/'state.json')
    if not isinstance(state.get('attempted'),dict) or not isinstance(state.get('completed'),dict):raise ValueError('原主线记录损坏，已阻止启动。')
    return root,state


def gate_mainline(state,stop_exists=False):
    active=state.get('active')
    if active:raise ValueError('主线已有战败或未结算记录：'+str(active.get('key',''))+'；先手动过关并补记，不自动重试。')
    if state.get('terminal') or stop_exists:
        raise ValueError('主线保留停止状态：'+str(state.get('status',''))+'；不会自动清除停止记录。')


def validate_run(settings,target,allow_reconcile=False):
    if settings.get('task') not in ('mainline','abyss','saint_3_7','dimension','theater','penguin'):raise ValueError('未知的任务类型。')
    if target.get('client') not in ('mumu','pc'):raise ValueError('所选客户端目标无效。')
    if settings.get('task')=='penguin':
        from penguin_core import quantity
        quantity(settings.get('penguin_quantity',''))
        if target['client']!='pc':raise ValueError('买企鹅目前仅接入实验性 PC 后台模式；MuMu未验收。')
        if settings.get('observe'):raise ValueError('买企鹅必须通过明确数量任务启动；不能从只读模式发送购买。')
    if settings.get('task')=='theater' and target['client']!='pc':raise ValueError('月光剧场目前仅接入实验性 PC 后台模式；MuMu尚未验收。')
    if target['client']=='pc' and settings.get('pc_input')!='messages':raise ValueError('桌面端输入模式无效；请使用后台窗口消息。')
    from assistant_portable import enabled,registered_root
    if not settings.get('data_dir') and registered_root() is None:
        return HOME/'observations',{'attempted':{},'completed':{}}
    root,state=history_gate(settings)
    if settings['task']=='mainline' and not settings.get('observe',False):
        if settings.get('start_policy')=='current_screen':
            return root,state
        from mainline_reconcile import pending_reconciliation
        if not (allow_reconcile and pending_reconciliation(state) and not (root/'STOP').exists()):
            gate_mainline(state,(root/'STOP').exists())
    return root,state


def reserve_abyss_entry(ledger,floor,details):
    """Durable intent must be saved before the one permitted entry input."""
    if not isinstance(floor,int) or floor<1:raise ValueError('深渊层数无效。')
    key=str(floor)
    from entry_journal import reserve_entry
    return reserve_entry(ledger,key,details)


def window_layout(workarea,screen_size):
    """Tk coordinates, with space reserved for the title bar and taskbar."""
    left,top,right,bottom=workarea
    aw=max(1,min(right-left,screen_size[0]));ah=max(1,min(bottom-top,screen_size[1]))
    width=max(1,min(640,aw-40));height=max(1,min(850,ah-70))
    return dict(width=width,height=height,x=left+max(0,aw-width-25),y=top+min(20,max(0,ah-height-30)),
                min_width=min(560,width),min_height=min(460,height),max_width=max(width,aw-30),max_height=max(height,ah-60))


def process_is_alive(pid):
    """Read-only liveness check; access errors never mean safe to replace."""
    import ctypes
    from ctypes import wintypes as w
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError('原工作进程编号无效；不重载。')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.GetExitCodeProcess.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.CloseHandle.restype = w.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:
            return False
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        code = w.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def load_theater_resume_request(run_id, home=HOME):
    """Explicit maintenance only: reuse an exited run, never create a new one.

    The normal Start/restart paths are unchanged. Caller must launch through
    the standard entry, after the old GUI exits; the new worker still takes
    the exclusive profile locks and revalidates the original target/fresh frame.
    """
    import re
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise ValueError('原任务编号无效；不新建任务替代。')
    home = Path(home).resolve()
    folder = (home/'runs'/run_id).resolve()
    if folder.parent != (home/'runs').resolve():
        raise ValueError('原任务目录不在受管理路径内。')
    active = read_json(home/'active-run.json', {})
    request = read_json(folder/'request.json', {})
    status = read_json(folder/'status.json', {})
    control = read_json(folder/'control.json', {})
    if (active.get('run_id') != run_id or Path(active.get('run_dir', '')).resolve() != folder
            or request.get('run_id') != run_id or Path(request.get('run_dir', '')).resolve() != folder
            or Path(request.get('home', '')).resolve() != home
            or status.get('run_id') != run_id or not (status.get('mode')=='stopped' or
                (status.get('mode')=='blocked' and request.get('settings',{}).get('task')=='mainline'))
            or control.get('run_id') != run_id or control.get('action') != 'stop'):
        raise ValueError('原任务尚未确认停止或身份不一致；不重载、不换run。')
    if process_is_alive(active.get('worker_pid')):
        raise ValueError('原工作进程尚未退出；不启动第二个写入者。')
    settings = request.get('settings', {})
    if settings.get('task')=='mainline':
        maintenance=read_json(folder/'mainline-maintenance-request.json',{})
        if maintenance.get('run_id')!=run_id or Path(maintenance.get('run_dir','')).resolve()!=folder:
            raise ValueError('缺少原主线run的明确维护请求；不按新开始替代。')
        root,_=validate_run(settings,request['target'],allow_reconcile=True)
        from mainline_maintenance import validate_maintenance
        validate_maintenance(maintenance,root,read_json(root/'state.json',{}),before_activation=True)
        return maintenance
    if (settings.get('task') != 'theater' or settings.get('observe') is not False
            or request.get('target', {}).get('client') != 'pc'):
        raise ValueError('原run维护重载目前仅限实验性PC月光剧场。')
    root, _ = validate_run(settings, request['target'], allow_reconcile=True)
    if (root/'STOP').exists():
        raise ValueError('存在停止标记；原run重载不能归档或绕过STOP。')
    state = read_json(root/'theater'/'state.json', {})
    entry = state.get('active')
    actions = [a for a in state.get('actions', []) if a.get('run_id') == run_id]
    # A user-started run may stop on identity recognition before its first
    # dispatch. Maintenance may reload that exact untouched run, but must not
    # resurrect an archived story or infer that a missing active means no input.
    def mentions_run(value):
        if isinstance(value, dict):
            return any(mentions_run(v) for v in value.values())
        if isinstance(value, list):
            return any(mentions_run(v) for v in value)
        return value == run_id
    # A sole standalone already-claimed notice dismissal is also zero-entry
    # maintenance. It never permits recovering archived entries or payment.
    standalone = (len(actions) == 1 and actions[0].get('kind') == 'close_reward_notice'
                  and actions[0].get('status') in ('sent', 'not_sent')
                  and actions[0].get('key') is None and actions[0].get('episode') is None
                  and isinstance(actions[0].get('evidence'), str) and actions[0]['evidence'])
    remaining = dict(state)
    remaining['actions'] = [a for a in state.get('actions', []) if a.get('run_id') != run_id]
    if (state.get('schema') == 1 and isinstance(state.get('registration_id'), str)
            and state['registration_id'] and 'active' in state and entry is None
            and all(isinstance(state.get(k), dict) for k in ('attempted', 'completed', 'entry_dispatches'))
            and all(isinstance(state.get(k), list) for k in ('actions', 'unresolved_entries'))
            and (not actions or standalone) and not mentions_run(remaining)):
        return request
    from theater_journal import current_pending_ticket
    if (entry and entry.get('phase') == 'await_ticket' and current_pending_ticket(state, run_id)
            and actions and all(a.get('status') in ('sent', 'not_sent') for a in actions)):
        return request
    if (not entry or entry.get('run_id') != run_id
            or entry.get('phase') not in ('await_guide', 'story')
            or not actions or any(a.get('status') not in ('sent', 'not_sent') for a in actions)):
        raise ValueError('原观览链缺失或存在发送结果未明的意图；不维护重载。')
    return request
