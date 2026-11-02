"""Shared settings/selection policy. No game input and no empty-history migration."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
CODE_ROOT=Path(__file__).resolve().parent
HOME=CODE_ROOT/'.local'/'assistant'


def read_json(path,default=None):
    path=Path(path)
    if not path.exists():return default
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(value,dict):raise ValueError('Invalid JSON object: '+str(path))
    return value


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(tmp,path)


def load_settings(home=HOME):
    saved=read_json(Path(home)/'settings.json')
    if saved is not None:return saved
    prefs=read_json(CODE_ROOT/'.local/pc/preferences.json',{})
    root=prefs.get('data_dir','')
    # Existing history is referenced in place, never copied/reset by the GUI.
    result={'client':'auto','task':'abyss','pc_input':'messages','limit':3,'observe':True,
            'data_dir':root,'worker_python':'','mumu':{}}
    hint=CODE_ROOT/'.local/python-path.txt'
    if hint.exists():result['worker_python']=hint.read_text(encoding='utf-8-sig').strip()
    if root:
        if not (Path(root)/'state.json').is_file():raise ValueError('Original mainline history is missing; no empty replacement created')
        cfg=read_json(Path(root)/'config.json',{})
        result['mumu']={k:cfg[k] for k in ('adb','serial','package') if k in cfg}
    return result


def select_target(client,targets):
    if client not in ('auto','mumu','pc'):raise ValueError('Unknown client selection')
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
    if settings.get('task') not in ('mainline','abyss'):raise ValueError('Unknown task')
    if not 1<=int(settings.get('limit',0))<=30:raise ValueError('本次上限须为1～30。')
    if target.get('client') not in ('mumu','pc'):raise ValueError('Invalid target')
    if target['client']=='pc' and settings.get('pc_input') not in ('messages','foreground'):raise ValueError('Invalid PC input mode')
    root,state=history_gate(settings)
    if settings['task']=='mainline' and not settings.get('observe',False):
        from mainline_reconcile import pending_reconciliation
        if not (allow_reconcile and pending_reconciliation(state) and not (root/'STOP').exists()):
            gate_mainline(state,(root/'STOP').exists())
    return root,state


def reserve_abyss_entry(ledger,floor,details):
    """Durable intent must be saved before the one permitted entry input."""
    if not isinstance(floor,int) or floor<1:raise ValueError('Invalid Abyss floor')
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
