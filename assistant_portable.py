"""Portable registration policy. No input, history reset, or implicit profile replacement."""
from pathlib import Path
from assistant_config import CODE_ROOT, HOME, atomic_json, read_json


def enabled():
    return (CODE_ROOT/'portable.json').is_file()


def registered_root(home=HOME):
    marker=Path(home)/'profile.json'
    if marker.exists():
        record=read_json(marker)
        value=record.get('data_dir')
        if not value:raise ValueError('本机进度登记损坏；不新建空记录。')
        root=Path(value)
        if not root.is_absolute():root=CODE_ROOT/root
        if not (root/'state.json').is_file():raise ValueError('已登记的进度丢失；不创建空历史替代。')
        return root.resolve()
    profiles=Path(home)/'profiles'
    if profiles.exists() and any(profiles.iterdir()):
        raise ValueError('发现未登记或不完整的旧进度；停止，不创建空记录。')
    return None


def relative_or_absolute(path):
    path=Path(path).resolve()
    try:return path.relative_to(CODE_ROOT.resolve()).as_posix()
    except ValueError:return str(path)


def save_settings(settings,home=HOME):
    value=dict(settings)
    value.pop('portable_first_use',None)
    if enabled():
        value['worker_python']='runtime/python.exe'
        if value.get('data_dir'):value['data_dir']=relative_or_absolute(value['data_dir'])
    atomic_json(Path(home)/'settings.json',value)


def register_existing(root,home=HOME):
    root=Path(root).resolve()
    state=read_json(root/'state.json')
    if not state or not isinstance(state.get('attempted'),dict) or not isinstance(state.get('completed'),dict):
        raise ValueError('所选目录没有有效的原始 state.json；未创建或清空记录。')
    current=registered_root(home)
    if current and current!=root:raise ValueError('本目录已登记其他进度；不允许换成空记录。')
    atomic_json(Path(home)/'profile.json',{'schema':1,'kind':'imported','data_dir':relative_or_absolute(root)})
    return root,state


def initialize_verified(proof,consent,home=HOME):
    """Only call with a fresh double-frame proof and explicit first-use consent."""
    import hashlib,time
    if not consent:raise ValueError('首次初始化需要明确确认；没有创建进度。')
    if registered_root(home):raise ValueError('已有登记，禁止重复初始化。')
    if not proof.get('server') or not str(proof.get('account_id','')).isdigit() or not 4<=len(str(proof['account_id']))<=20 or not 0<=time.time()-proof.get('checked_at',0)<=120:
        raise ValueError('缺少有效的当前账号证明；没有创建进度。')
    digest=hashlib.sha256((proof['server']+'\0'+proof['account_id']).encode()).hexdigest()[:24]
    root=Path(home)/'profiles'/digest
    if root.exists():raise ValueError('账号进度目录已存在；禁止覆盖。')
    # Register intent before creating the profile: interrupted setup must fail closed.
    atomic_json(Path(home)/'profile.json',{'schema':1,'kind':'managed','data_dir':relative_or_absolute(root)})
    root.mkdir(parents=True,exist_ok=False)
    state={'schema':1,'started_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'attempted':{},'completed':{},'active':None,'victories':0,
           'initialization':'first_use_verified_account','pc_profile_binding':{'server':proof['server'],'account_id':proof['account_id'],'bound_at':time.time()}}
    atomic_json(root/'state.json',state)
    return root,state
