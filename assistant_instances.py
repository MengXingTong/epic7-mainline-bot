"""Multi-window slots and per-client leases. No discovery or game input here."""
from __future__ import annotations
from contextlib import contextmanager
import ctypes
import hashlib
import os
from pathlib import Path

from assistant_config import HOME, atomic_json, read_json


class NamedLeases:
    """Handle lifetime is the lease; Windows releases it on process exit."""
    def __init__(self):
        from ctypes import wintypes as w
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, w.BOOL, w.LPCWSTR]
        self.kernel.CreateMutexW.restype = w.HANDLE
        self.kernel.OpenMutexW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
        self.kernel.OpenMutexW.restype = w.HANDLE
        self.kernel.CloseHandle.argtypes = [w.HANDLE]
        self.kernel.CloseHandle.restype = w.BOOL

    def acquire(self, name):
        ctypes.set_last_error(0)
        handle = self.kernel.CreateMutexW(None, False, name)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == 183:
            self.release(handle)
            return None
        return handle

    def exists(self, name):
        handle = self.kernel.OpenMutexW(0x100000, False, name)
        if handle:
            self.release(handle)
            return True
        error = ctypes.get_last_error()
        if error == 2:
            return False
        raise ctypes.WinError(error)

    def release(self, handle):
        if not self.kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())


def slot_home(base, number):
    if type(number) is not int or number < 1:
        raise ValueError('助手编号必须是正整数。')
    base = Path(base).resolve()
    return base if number == 1 else base/'instances'/str(number)


def homes(base):
    base = Path(base).resolve()
    yield 1, base
    parent = base/'instances'
    if parent.exists():
        for path in sorted(parent.iterdir()):
            if path.is_dir() and path.name.isdecimal() and int(path.name) >= 2:
                yield int(path.name), path.resolve()


def worker_alive(home):
    active = read_json(Path(home)/'active-run.json', {})
    if not active:
        return False
    from assistant_config import process_is_alive
    return process_is_alive(active.get('worker_pid'))


class WindowSlot:
    def __init__(self, base, number, api, handle):
        self.base = Path(base).resolve()
        self.number = number
        self.home = slot_home(base, number)
        self.api, self.handle = api, handle

    def close(self):
        if self.handle is not None:
            self.api.release(self.handle)
            self.handle = None


def reserve_window(base=HOME, number=None, *, api=None, alive=worker_alive, legacy=True):
    """Reuse the lowest idle persistent slot; never reset its stored history."""
    api = api or NamedLeases()
    base = Path(base).resolve()
    if number is not None:
        slot_home(base, number)  # Validate even when a caller supplies a bad slot.
    digest = hashlib.sha256(os.path.normcase(str(base)).encode()).hexdigest()
    old_ui = legacy and any(api.exists(name) for name in (
        r'Local\Epic7UnifiedAssistant', r'Local\EpicSevenAbyssPilot.Panel'))
    current = number or 1
    while True:
        handle = api.acquire(r'Local\Epic7Assistant.Window.'+digest+'.'+str(current))
        if handle is not None:
            try:
                busy = (current == 1 and old_ui) or alive(slot_home(base, current))
            except BaseException:
                api.release(handle)
                raise
            if not busy:
                return WindowSlot(base, current, api, handle)
            api.release(handle)
        if number is not None:
            raise ValueError(f'助手 #{number} 的界面或工作进程仍在运行；不接管、不停止原任务。')
        current += 1


def resume_slot(base, run_id):
    import re
    if not isinstance(run_id, str) or not re.fullmatch(r'[0-9a-f]{32}', run_id):
        raise ValueError('原任务编号无效。')
    matches = [number for number, home in homes(base) if (home/'runs'/run_id/'request.json').is_file()]
    if len(matches) != 1:
        raise ValueError('未找到唯一原任务目录；不创建新记录替代。')
    return matches[0]


def target_key(target):
    """Physical input endpoint, not task/package/label; localhost aliases agree."""
    if target.get('client') == 'pc':
        hwnd = target.get('hwnd')
        if type(hwnd) is not int or hwnd <= 0:
            raise ValueError('缺少有效的所选游戏窗口。')
        return 'pc:'+str(hwnd)
    if target.get('client') == 'mumu':
        serial = str(target.get('serial', '')).strip().lower()
        if not serial:
            raise ValueError('缺少模拟器实例地址。')
        host, sep, port = serial.rpartition(':')
        if sep and host in ('localhost', '127.0.0.1', '[::1]') and port.isdecimal():
            serial = '127.0.0.1:'+str(int(port))
        return 'mumu:'+serial
    raise ValueError('未知客户端；不分配输入锁。')


def history_key(target):
    # HWND alone is the concurrent lock, but recycled HWNDs cannot inherit history.
    key = target_key(target)
    if target['client'] == 'pc':
        key += ':'+str(target['pid'])+':'+str(target['created'])
    return hashlib.sha256(key.encode()).hexdigest()


def legacy_request(home):
    active = read_json(Path(home)/'active-run.json', {})
    if not active:
        return None
    folder = Path(active.get('run_dir', '')).resolve()
    if folder.parent != (Path(home)/'runs').resolve():
        raise ValueError('原工作进程目录不在受管理路径内。')
    request = read_json(folder/'request.json', {})
    if request.get('run_id') != active.get('run_id'):
        raise ValueError('原工作进程请求身份不一致。')
    return request


@contextmanager
def exclusive_target(target, base=HOME, *, api=None, alive=worker_alive):
    api = api or NamedLeases()
    digest = hashlib.sha256(target_key(target).encode()).hexdigest()
    handle = api.acquire(r'Local\Epic7Assistant.Target.'+digest)
    if handle is None:
        raise RuntimeError('该游戏窗口/模拟器已由另一个助手控制；请选择其他客户端实例。')
    try:
        # Pre-upgrade workers have no target lease. Do not touch or stop them.
        for _, home in homes(base):
            active = read_json(home/'active-run.json', {})
            if active and active.get('worker_pid') != os.getpid() and alive(home):
                request = legacy_request(home)
                if request and target_key(request['target']) == target_key(target):
                    raise RuntimeError('该客户端仍有原助手任务运行；不接管、不发送输入。')
        yield
    finally:
        api.release(handle)


def _profile_path(value):
    if not isinstance(value,str) or not value.strip():
        raise ValueError('客户端进度关联损坏；不选择替代记录。')
    root=Path(value)
    if not root.is_absolute():
        from assistant_config import CODE_ROOT
        root=CODE_ROOT/root
    return root.resolve()


def _target_profile_bindings(base):
    """Only persisted target registrations are associations, not UI caches."""
    rows=[]
    for _,home in homes(base):
        for key,row in read_json(home/'target-profiles.json',{}).items():
            if not isinstance(row,dict):raise ValueError('客户端进度关联损坏；不选择替代记录。')
            rows.append((key,_profile_path(row.get('data_dir')),home))
    return rows


def known_target_root(target, base):
    """Reuse verified associations; a request cache cannot bind another client."""
    from assistant_portable import registered_root
    roots=set();key=history_key(target);bindings=_target_profile_bindings(base)
    owners={}
    for registered_key,root,_ in bindings:
        owners.setdefault(root,set()).add(registered_key)
        if registered_key==key:
            if not (root/'state.json').is_file():
                raise ValueError('客户端原进度丢失；不新建空记录替代。')
            roots.add(root)
    for _,home in homes(base):
        request=legacy_request(home)
        if request and history_key(request['target'])==key:
            value=request.get('settings',{}).get('data_dir')
            root=_profile_path(value) if value else registered_root(home)
            if root:
                # A new Start is published before worker profile validation. Its
                # cached settings may still name the previous selected client.
                # Preserve the request, but do not promote that cache to a bind.
                if owners.get(root) and key not in owners[root]:continue
                if not (root/'state.json').is_file():
                    raise ValueError('客户端旧任务进度丢失；不创建替代。')
                roots.add(root)
    if len(roots)>1:
        raise ValueError('该客户端对应多个原记录；请检查关联，不自动选择或新建。')
    return next(iter(roots),None)


def resolve_target_profile(settings,target,base):
    """Route a proven stale cache only to this client's unique original root.

    Ambiguous real bindings, explicit imports and unowned caches never get an
    automatic preference. This function does not write or create any history.
    """
    value=dict(settings);known=known_target_root(target,base)
    saved=value.get('data_dir');cached=_profile_path(saved) if saved else None
    if cached==known or known is None and cached is None:return value,None
    key=history_key(target);owners={registered_key for registered_key,root,_ in _target_profile_bindings(base) if root==cached}
    choice=value.get('profile_choice') or {}
    explicit=(choice.get('kind')=='explicit_import' and bool(choice.get('data_dir'))
              and _profile_path(choice['data_dir'])==cached and choice.get('target_key') in (None,key))
    if known is None:
        if owners and key not in owners:
            raise ValueError('所选客户端尚无已关联原进度；不能使用另一个客户端的缓存记录。')
        return value,None
    if cached is not None and (explicit or not owners or key in owners):
        raise ValueError('所选客户端已有不同原进度；不覆盖明确选择或不明来源的记录。')
    value.update(data_dir=str(known),portable_first_use=False)
    audit=dict(schema=1,reason='selected_target_original_profile',target_key=key,
               previous_data_dir=str(cached) if cached else None,resolved_data_dir=str(known),
               previous_registered_target_keys=sorted(owners),history_mutated=False)
    return value,audit


def remember_target(target, root, home):
    from assistant_portable import relative_or_absolute
    path = Path(home)/'target-profiles.json'
    bindings = read_json(path, {})
    bindings[history_key(target)] = {'data_dir': relative_or_absolute(root)}
    atomic_json(path, bindings)


def abyss_history_path(request):
    """Cross-slot reuse also references the existing Abyss ledger, never resets it."""
    current=Path(request['home']).resolve()
    base=request.get('instance_base',os.environ.get('EPIC7_ASSISTANT_BASE'))
    value=request.get('settings',{}).get('data_dir')
    if not base or not value:
        return current/'abyss-history.json'
    root=Path(value).resolve()
    from assistant_portable import registered_root
    candidates=set()
    for _,home in homes(base):
        ledger=home/'abyss-history.json'
        if not ledger.exists():continue
        known=registered_root(home)
        if known is None:
            saved=read_json(home/'settings.json',{}).get('data_dir')
            if saved:
                known=Path(saved)
                if not known.is_absolute():
                    from assistant_config import CODE_ROOT
                    known=CODE_ROOT/known
        if known is not None and known.resolve()==root:candidates.add(ledger)
    if len(candidates)>1:
        raise ValueError('同一原进度存在多个深渊历史；不自动覆盖或重建。')
    return next(iter(candidates),current/'abyss-history.json')
