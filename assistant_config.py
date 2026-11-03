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
    if settings.get('task') not in ('mainline','abyss','saint_3_7'):raise ValueError('未知的任务类型。')
    if target.get('client') not in ('mumu','pc'):raise ValueError('所选客户端目标无效。')
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
    if key in ledger['attempted']:raise ValueError('该层已有入场记录，不重复开战。')
    ledger['attempted'][key]=dict(details)


def window_layout(workarea,screen_size):
    """Tk coordinates, with space reserved for the title bar and taskbar."""
    left,top,right,bottom=workarea
    aw=max(1,min(right-left,screen_size[0]));ah=max(1,min(bottom-top,screen_size[1]))
    width=max(1,min(640,aw-40));height=max(1,min(850,ah-70))
    return dict(width=width,height=height,x=left+max(0,aw-width-25),y=top+min(20,max(0,ah-height-30)),
                min_width=min(560,width),min_height=min(460,height),max_width=max(width,aw-30),max_height=max(height,ah-60))
