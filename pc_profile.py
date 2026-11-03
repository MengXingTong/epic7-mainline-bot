"""Pure OCR account preflight. It does not select a server or send any input."""
import time

def account_preflight(frame,settings,window,checked_at=None):
    from runner import resource_warning
    if resource_warning(frame):raise ValueError('资源提示优先，已停止旧版桌面端账号预检。')
    if not settings.get('server') or not str(settings.get('account_id','')).isdigit():
        raise ValueError('旧版工具需要先在本机配置服务器和纯数字服务器账号编号。')
    if not frame.find('账号信息',(120,90,500,210)) or not frame.find('服务器账号编号',(100,480,650,640)):
        raise ValueError('旧版桌面端预检前，请打开游戏内的账号与服务器信息页。')
    server=frame.find(settings['server'],(900,395,1560,490),exact=True)
    uid=frame.find(str(settings['account_id']),(1150,495,1560,620),exact=True)
    if not server or server['score']<.85 or not uid or uid['score']<.90:
        raise ValueError('读取到的桌面端服务器或账号编号与本机配置不完全一致。')
    return dict(server=settings['server'],account_id=str(settings['account_id']),window=window.identity(),checked_at=checked_at if checked_at is not None else time.time())
