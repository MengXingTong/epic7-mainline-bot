"""Bounded, read-only OCR planning for the one-click PC startup navigation.

No server selection, account switching, resource buttons or generic confirmation.
The native backend, not this planner, enforces frame/focus/geometry guards.
"""
import re

class StartupBlocked(RuntimeError):
    pass

def observed_account(frame, window, checked_at=None):
    """Read the account actually logged in; never ask users to type its fields."""
    import time
    from runner import resource_warning
    if resource_warning(frame):
        raise StartupBlocked('资源提示优先，停止启动核对')
    if not frame.find('账号信息', (120,90,500,210)) or not frame.find('服务器账号编号', (100,480,650,640)):
        raise StartupBlocked('当前不是可核实的账号信息页')
    servers=[w for w in frame.words if 900<=w['x']<=1560 and 395<=w['y']<=490 and w['score']>=.90
             and w['text'].strip() not in ('切换服务器','选择服务器','更换服务器')
             and (re.fullmatch(r'.{1,16}服务器',w['text'].strip()) or w['text'].strip()=='原石铸界')]
    ids=[w for w in frame.words if 1150<=w['x']<=1560 and 495<=w['y']<=620
         and w['score']>=.90 and re.fullmatch(r'\d{4,20}',w['text'].strip())]
    if len(servers)!=1 or len(ids)!=1:
        raise StartupBlocked('服务器/账号字段不清晰或存在歧义；不猜测、不切服')
    return dict(server=servers[0]['text'].strip(),account_id=ids[0]['text'].strip(),
                window=window.identity(),checked_at=time.time() if checked_at is None else checked_at)

def navigation_target(frame):
    """Only three cost-free navigation targets; unknown UI is never clicked."""
    from runner import classify,resource_warning
    if resource_warning(frame):raise StartupBlocked('资源提示优先，禁止导航')
    if frame.any('登录','登陆','验证码','选择服务器','切换服务器','账号认证','密码'):
        raise StartupBlocked('请先手动登录；不会处理登录或服务器选择')
    mode=classify(frame)
    if mode in ('defeat','unknown_dialog','skip_confirm','settlement','rankup','story','battle'):
        raise StartupBlocked('当前不是启动导航页面；不打断战斗或确认弹窗')
    # Settings sidebar only. This does not click account management/security fields.
    account=frame.find('账号信息',(0,120,420,850),exact=True)
    if account and frame.find(r'^(设置|设定)$',(0,0,500,160)) and frame.find(r'游戏设置|画面设置|声音设置',(0,100,420,850)):
        return 'account_tab',(account['x'],account['y'])
    # Expanded navigation menu: require several independent, exact menu labels.
    menu_labels=('英雄','背包','召唤','圣域','商店','骑士团','好友','图鉴','宠物','成就')
    hits=sum(bool(frame.find(label,(800,70,1599,820),exact=True)) for label in menu_labels)
    if hits>=4:
        setting=frame.find('设置',(1400,630,1599,820),exact=True)
        if setting:return 'settings',(setting['x'],setting['y'])
        # Require a hollow white gear glyph at the known settings-button area.
        import cv2,numpy as np
        glyph=frame.image[690:790,1470:1575]
        hsv=cv2.cvtColor(glyph,cv2.COLOR_BGR2HSV)
        mask=cv2.inRange(hsv,np.array([0,0,175]),np.array([179,90,255]))
        contours,hierarchy=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
        if hierarchy is not None:
            for i,c in enumerate(contours):
                parent=hierarchy[0][i][3];x,y,w,h=cv2.boundingRect(c);area=cv2.contourArea(c)
                if parent<0 or not 20<=area<=450 or not .65<=w/max(h,1)<=1.5:continue
                px,py,pw,ph=cv2.boundingRect(contours[parent])
                if not (20<=pw<=80 and 20<=ph<=80 and pw>=w*1.5 and ph>=h*1.5):continue
                cx,cy=x+w/2+1470,y+h/2+690
                if abs(cx-1520)<=18 and abs(cy-736)<=18:return 'settings',(cx,cy)
        raise StartupBlocked('未识别设置文字或齿轮，保留菜单现场，不盲点')
    if mode not in ('map','lobby'):
        raise StartupBlocked('请把游戏放在主线地图或大厅后启动；未识别画面不点击')
    # Positive blue navigation-grid signature in its dedicated top-right area.
    import cv2,numpy as np
    crop=frame.image[8:76,1510:1599]
    hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
    mask=cv2.inRange(hsv,np.array([85,100,100]),np.array([135,255,255]))
    contours,hierarchy=cv2.findContours(mask,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    holes=[]
    if hierarchy is not None:
        for i,c in enumerate(contours):
            x,y,w,h=cv2.boundingRect(c)
            if hierarchy[0][i][3]>=0 and 5<=w<=23 and 5<=h<=23 and .6<=w/h<=1.6:
                holes.append((x+w/2,y+h/2))
    # Four hollow squares; one may be obscured by the notification dot.
    if not 3<=len(holes)<=4:
        raise StartupBlocked('未可靠识别右上角导航图标；不使用盲点坐标')
    xs=[p[0] for p in holes];ys=[p[1] for p in holes]
    if max(xs)-min(xs)<12 or max(ys)-min(ys)<10:
        raise StartupBlocked('导航图标形状不符')
    return 'menu',(1510+(min(xs)+max(xs))/2,8+(min(ys)+max(ys))/2)
