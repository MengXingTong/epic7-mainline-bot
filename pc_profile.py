"""Pure OCR account preflight. It does not select a server or send any input."""
import time

def account_preflight(frame,settings,window,checked_at=None):
    from runner import resource_warning
    if resource_warning(frame):raise ValueError('Resource warning overrides PC account preflight')
    if not settings.get('server') or not str(settings.get('account_id','')).isdigit():
        raise ValueError('Configure the expected server and numeric server account ID locally')
    if not frame.find('账号信息',(120,90,500,210)) or not frame.find('服务器账号编号',(100,480,650,640)):
        raise ValueError('Open the in-game account/server information page before PC preflight')
    server=frame.find(settings['server'],(900,395,1560,490),exact=True)
    uid=frame.find(str(settings['account_id']),(1150,495,1560,620),exact=True)
    if not server or server['score']<.85 or not uid or uid['score']<.90:
        raise ValueError('Observed PC server/account ID does not exactly match local configuration')
    return dict(server=settings['server'],account_id=str(settings['account_id']),window=window.identity(),checked_at=checked_at if checked_at is not None else time.time())
