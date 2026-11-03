"""Backend-independent frames/actions shared by both tasks."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib, json, subprocess, time
from pathlib import Path
import numpy as np
import cv2
from PIL import Image
from pc_backend import PcSafetyError

@dataclass
class FrameSnapshot:
    image: Image.Image
    binding: object
    captured_at: float
    input_tick: int|None=None

class UnifiedTransport:
    def __init__(self,settings,target,check=lambda:None):
        self.settings=settings;self.target=target;self.check=check
        self.window=None;self.frame=None;self.frame_window=None;self.last_input=None
        self.background=True
        if target['client']=='pc':
            if settings.get('pc_input')!='messages':raise PcSafetyError('前台模式已移除；请使用后台窗口消息。')
            from pc_message_backend import MessageWin32Api
            self.api=MessageWin32Api()
            rows=self.api.windows(target['exe'],target['title'])
            if len(rows)!=1 or rows[0].hwnd!=target['hwnd'] or rows[0].pid!=target['pid'] or rows[0].created!=target['created']:
                raise PcSafetyError('所选桌面端实例已变化，已停止操作。')
            self.window=rows[0]
        else:self.api=None

    def adb(self,*args,timeout=15):
        self.check()
        r=subprocess.run([self.settings['mumu']['adb'],'-s',self.target['serial'],*map(str,args)],capture_output=True,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode:raise RuntimeError(r.stderr.decode('utf-8',errors='replace')[:400])
        return r.stdout

    def ensure(self):
        self.check()
        if self.api:
            rows=self.api.windows(self.target['exe'],self.target['title'])
            if len(rows)!=1 or rows[0].identity()!=self.window.identity():raise PcSafetyError('桌面端进程或窗口已变化，已停止操作。')
            if not self.api.ready(rows[0]):raise PcSafetyError('桌面端后台窗口不可用或已最小化，已停止操作。')
            return rows[0]
        activity=self.adb('shell','dumpsys','activity','activities').decode('utf-8',errors='replace')
        lines=[l for l in activity.splitlines() if 'topResumedActivity' in l or 'mResumedActivity' in l]
        if not any(self.target['package']+'/' in l for l in lines):raise RuntimeError('MuMu前台Android应用不是已绑定游戏，停止输入。')
        return self.target['serial']

    def input_tick(self):return None  # Both supported modes are background-only.

    def capture(self):
        before=self.ensure();at=time.monotonic()
        tick=self.input_tick()
        if self.api:raw=self.api.capture(before)
        else:raw=cv2.imdecode(np.frombuffer(self.adb('exec-out','screencap','-p'),np.uint8),cv2.IMREAD_COLOR)
        if raw is None:raise RuntimeError('未取得有效的客户端画面。')
        h,w=raw.shape[:2]
        if w<640 or h<360 or abs(w/h-16/9)>.035:raise RuntimeError('请使用至少640×360的16:9横屏客户区。')
        after=self.ensure()
        if before!=after:raise RuntimeError('截图期间客户端位置或尺寸发生变化，已停止操作。')
        f=FrameSnapshot(Image.fromarray(raw[:,:,::-1]),after,at,tick)
        self.last_input=tick
        self.frame=f;self.frame_window=after
        return f

    def _fresh(self,f):
        self.check()
        if f is not self.frame or time.monotonic()-f.captured_at>5:raise RuntimeError('画面已过期或已使用；不发送输入。')
        if self.ensure()!=f.binding:raise RuntimeError('观察后客户端位置或尺寸发生变化，已停止操作。')
        if f.input_tick is not None and self.input_tick()!=f.input_tick:raise RuntimeError('检测到手动输入，当前画面校验已失效。')

    def tap(self,f,token,ordinary_gate=False):
        self._fresh(f)
        x,y=token.center;w,h=f.image.size
        if not (0<=x<w and 0<=y<h):raise RuntimeError('点击位置超出游戏客户区，已拒绝操作。')
        if ordinary_gate and not (.80*w<=x<=.99*w and .20*h<=y<=.53*h):raise RuntimeError('只允许进入右上方的普通深渊入口。')
        self.frame=None # Consume before any input; failure never retries the same frame.
        if self.api:
            s=f.binding;px=s.x+int(x*s.width/w);py=s.y+int(y*s.height/h)
            if not self.api.point_is_target(s,px,py):raise RuntimeError('桌面端目标已不再符合输入条件。')
            self.api.move(px,py);self.check()
            if not self.api.ready(s):raise RuntimeError('桌面端输入目标已变化，已停止操作。')
            try:
                self.api.button(True)
            finally:self.api.button(False)
            self.last_input=self.input_tick()
        else:self.adb('shell','input','tap',round(x),round(y))

    def swipe(self,f):
        self._fresh(f);self.frame=None
        w,h=f.image.size
        if not self.api:self.adb('shell','input','swipe',round(w*.88),round(h*.60),round(w*.34),round(h*.60),500);return
        s=f.binding
        start=(s.x+round(s.width*.88),s.y+round(s.height*.60));end=s.x+round(s.width*.34)
        self.api.move(*start)
        try:
            self.api.button(True)
            for i in range(1,25):
                self.check()
                if not self.api.ready(s):raise RuntimeError('拖动列表期间桌面端目标发生变化，已停止操作。')
                self.api.move(round(start[0]+(end-start[0])*i/24),start[1]);time.sleep(.02)
        finally:self.api.button(False)
        self.last_input=self.input_tick()

class AdbNavigationBackend:
    """Account/reconciliation navigation only; no stage-entry planner lives here."""
    def __init__(self,settings,target,check=lambda:None):
        from types import SimpleNamespace
        self.transport=UnifiedTransport(settings,target,check);self.latest=None;self.allowed=False
        identity={'client':'mumu','serial':target['serial'],'package':target['package']}
        self.window=SimpleNamespace(identity=lambda:dict(identity));self.digest=None
    def capture(self):
        self.latest=self.transport.capture();raw=np.array(self.latest.image)[:,:,::-1].copy()
        self.digest=hashlib.sha256(cv2.resize(raw,(1600,900)).tobytes()).digest()
        return raw
    def navigate_account(self,frame):
        from pc_startup import navigation_target
        if self.digest!=hashlib.sha256(frame.image.tobytes()).digest():raise RuntimeError('MuMu账号导航画面不匹配。')
        kind,xy=navigation_target(frame);self._tap(*xy);return kind
    def authorize_selected_target(self,target):
        expected={k:self.transport.target[k] for k in ('serial','package')}
        if {k:target[k] for k in ('serial','package')}!=expected:raise RuntimeError('所选 MuMu 模拟器实例已变化，已停止操作。')
        self.transport.ensure();self.allowed=True
    def authorize(self,proof):
        if proof.get('window')!=self.window.identity() or not 0<=time.time()-proof.get('checked_at',0)<=120:raise RuntimeError('MuMu账号核对已失效。')
        self.allowed=True
    def _tap(self,x,y):
        from abyss_core import Token
        if self.latest is None:raise RuntimeError('没有可用于导航的新鲜模拟器画面。')
        w,h=self.latest.image.size
        token=Token('verified_navigation',x*w/1600-1,y*h/900-1,2,2)
        self.transport.tap(self.latest,token)
    def ensure(self):
        if not self.allowed:raise RuntimeError('MuMu历史核对尚未通过账号授权。')
        self.transport._fresh(self.latest)
    def tap(self,x,y):self.ensure();self._tap(x,y)
    def back(self):
        self.ensure();self.transport.frame=None;self.transport.adb('shell','input','keyevent','4')
