"""Experimental STOVE PC transport. Importing this module never touches Windows.

Native API calls are isolated behind an injectable adapter for offline tests.
No activation, login, server switching, installation or privilege bypass is done.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
import os, time, hashlib
import numpy as np

class PcSafetyError(RuntimeError):
    pass

class FrameExpired(PcSafetyError):
    """An unconsumed observation exceeded its age limit; never extends its TTL."""

class NavigationFrameExpired(FrameExpired):
    """A whitelisted non-entry tap expired before any button-down was sent."""

class InputBusy(PcSafetyError):
    """Physical input blocks further sends; a drag/hold may already be down."""

class InputDeliveryError(PcSafetyError):
    """Delivery failed or is uncertain. Preserve intent; never replay an entry."""

class TapNotSent(InputBusy):
    """A tap was cancelled before its button-down; no entry input was sent."""

class NavigationInputDeferred(TapNotSent):
    """A whitelisted non-entry UI tap was cancelled before button-down.

    Only a fresh plan may replace it. No entry, journaled close, drag, hold,
    uncertain send or previous observation is authorized by this signal.
    """

@dataclass(frozen=True)
class WindowSnapshot:
    hwnd: int
    pid: int
    exe: str
    created: int
    x: int
    y: int
    width: int
    height: int
    dpi: int = 96

    def identity(self):
        return dict(hwnd=self.hwnd,pid=self.pid,exe=os.path.normcase(os.path.abspath(self.exe)),created=self.created)

    def point(self,x,y):
        if not (0 <= x < 1600 and 0 <= y < 900):
            raise PcSafetyError('桌面端目标超出标准化游戏客户区。')
        return self.x+min(self.width-1,int(x*self.width/1600)), self.y+min(self.height-1,int(y*self.height/900))

class PcBackend:
    def __init__(self,cfg,stop_path,api=None,clock=time.monotonic,read_only=False):
        self.cfg=cfg;self.stop_path=Path(stop_path);self.clock=clock;self.read_only=read_only
        self.api=api if api is not None else Win32Api()
        self.window=None;self.frame_window=None;self.frame_at=None
        self.allowed=False
        self.navigation_digest=None
        self.frame_viewport=None

    def _stop_check(self):
        if self.stop_path.exists():raise PcSafetyError('检测到停止标记；已禁用桌面端输入。')

    def snapshot(self):
        if not self.read_only:self._stop_check()
        candidates=self.api.windows(self.cfg['game_exe'],self.cfg.get('window_title','第七史诗'))
        selected=self.cfg.get('selected_window')
        if selected is not None:candidates=[s for s in candidates if s.identity()==selected]
        elif self.window is not None:candidates=[s for s in candidates if s.identity()==self.window.identity()]
        if len(candidates)!=1:raise PcSafetyError('必须找到唯一已授权的桌面端游戏窗口；不会切换到其他实例。')
        current=candidates[0]
        if current.width<640 or current.height<360:raise PcSafetyError('桌面端游戏客户区过小，请放大窗口。')
        ratio=current.width/current.height
        if not 1.4<=ratio<=2.4:raise PcSafetyError('不支持当前桌面端游戏客户区的宽高比。')
        if abs(ratio-16/9)>.03 and self.cfg.get('viewport_mode')!='auto' and not self.cfg.get('allow_stretched_client',False):
            raise PcSafetyError('非 16:9 客户区需先在本机验证，并明确启用拉伸客户区配置。')
        if self.window is not None and current.identity()!=self.window.identity():
            raise PcSafetyError('桌面端游戏进程或窗口已变化；请停止并重选实例。')
        if not self.api.ready(current):
            reason=getattr(self.api,'last_unready_reason','') or '窗口未满足当前输入方式的可用条件'
            raise PcSafetyError('桌面端窗口暂不可用：'+reason+'。')
        self.window=current
        return current

    def capture(self):
        before=self.snapshot();raw=self.api.capture(before)
        after=self.snapshot()
        if before!=after:raise PcSafetyError('截图期间桌面端窗口位置或尺寸发生变化。')
        if raw.shape!=(before.height,before.width,3):raise PcSafetyError('桌面端截图尺寸与游戏客户区不一致。')
        self.frame_window=after;self.frame_at=self.clock()
        from client_viewport import Viewport,pc_viewport,crop_viewport
        self.frame_viewport=pc_viewport(raw) if self.cfg.get('viewport_mode')=='auto' else Viewport(0,0,before.width,before.height)
        raw=crop_viewport(raw,self.frame_viewport)
        import cv2
        self.navigation_digest=hashlib.sha256(cv2.resize(raw,(1600,900)).tobytes()).digest()
        return raw

    def authorize(self,preflight,max_age=120):
        if self.read_only:raise PcSafetyError('只读桌面端后端不能授权执行输入。')
        current=self.snapshot()
        if not self.cfg.get('experimental_input_enabled',False):
            raise PcSafetyError('配置中未启用实验性桌面端输入。')
        if time.time()-preflight.get('checked_at',0)>max_age or preflight.get('checked_at',0)>time.time()+5:
            raise PcSafetyError('桌面端账号预检已过期。')
        for key in ('server','account_id'):
            if not self.cfg.get(key) or preflight.get(key)!=self.cfg[key]:
                raise PcSafetyError('桌面端账号或服务器核验凭据与配置不符。')
        if preflight.get('window')!=current.identity():raise PcSafetyError('桌面端预检凭据属于其他窗口或进程。')
        self.allowed=True

    def authorize_selected_target(self,identity):
        """Explicit GUI target selection, independent of server/account OCR."""
        if self.read_only:raise PcSafetyError('只读桌面端后端不能授权执行输入。')
        if self.cfg.get('authorization_mode')!='selected_target' or not self.cfg.get('experimental_input_enabled',False):
            raise PcSafetyError('未启用所选窗口授权。')
        current=self.snapshot()
        if current.identity()!=identity:raise PcSafetyError('所选桌面端窗口或进程已变化；不发送输入。')
        self.allowed=True

    def navigate_account(self,frame):
        """Restricted preflight navigation, never general input authorization."""
        from pc_startup import navigation_target
        if self.read_only:raise PcSafetyError('只读桌面端后端不执行导航。')
        if not self.cfg.get('experimental_input_enabled',False):raise PcSafetyError('实验性桌面端输入未启用。')
        self._stop_check()
        if self.frame_at is None or self.clock()-self.frame_at>5:raise PcSafetyError('启动画面已过期，已拒绝操作。')
        if hashlib.sha256(frame.image.tobytes()).digest()!=self.navigation_digest:
            raise PcSafetyError('启动导航画面与原生窗口观察结果不一致。')
        kind,xy=navigation_target(frame)
        current=self.snapshot()
        if current!=self.frame_window:raise PcSafetyError('启动期间窗口位置或尺寸发生变化。')
        point=current.point(*xy)
        if not self.api.point_is_target(current,*point):raise PcSafetyError('启动导航目标被遮挡，已拒绝操作。')
        self.api.move(*point)
        if self.snapshot()!=current or not self.api.point_is_target(current,*point):
            raise PcSafetyError('按下鼠标前启动目标已变化。')
        self._stop_check()
        if self.clock()-self.frame_at>5:raise PcSafetyError('按下鼠标前启动画面已过期。')
        self.frame_at=None;self.navigation_digest=None
        try:self.api.button(True)
        finally:self.api.button(False)
        return kind

    def ensure(self):
        if self.read_only:raise PcSafetyError('只读桌面端后端不发送输入。')
        self._stop_check()
        if not self.allowed:raise PcSafetyError('桌面端输入缺少已核实的目标授权。')
        if self.frame_at is None:
            raise PcSafetyError('桌面端画面已过期；未发送输入。')
        current=self.snapshot()
        if current!=self.frame_window:raise PcSafetyError('观察后桌面端窗口发生移动、缩放或显示比例变化。')
        if self.clock()-self.frame_at>5:
            raise FrameExpired('桌面端画面已过期；未发送输入。')
        return current

    def input_block_reason(self):
        current=self.snapshot()
        if self.frame_window is not None and current!=self.frame_window:
            raise PcSafetyError('等待输入期间窗口几何发生变化；请确认后继续并重新截图。')
        query=getattr(type(self.api),'input_block_reason',None)
        return query(self.api,current) if query else ''

    def tap(self,x,y):
        current=self.ensure();point=self.frame_point(current,x,y)
        if not self.api.point_is_target(current,*point):raise PcSafetyError('桌面端点击位置被其他窗口遮挡。')
        self.api.move(*point)
        self.ensure()
        if not self.api.point_is_target(current,*point):raise PcSafetyError('按下鼠标前桌面端目标已变化。')
        self.frame_at=None  # Consume even when the input result is unknown.
        try:
            self.api.button(True)
        except InputBusy as exc:
            # MessageWin32Api.button checks ownership only BEFORE WM_LBUTTONDOWN.
            # Errors with uncertain delivery keep the original intent blocked.
            raise TapNotSent(str(exc)) from exc
        finally:self.api.button(False)

    def frame_point(self,current,x,y):
        if self.frame_viewport is None:return current.point(x,y)
        try:px,py=self.frame_viewport.point(x,y)
        except ValueError as exc:raise PcSafetyError(str(exc)) from exc
        return current.x+px,current.y+py

    def back(self):
        self.ensure();self.frame_at=None;self.api.escape()

    def drag(self,x1,y1,x2,y2,seconds=.45):
        if not .1<=seconds<=1:raise PcSafetyError('桌面端拖动时长不符合允许范围。')
        current=self.ensure();start=self.frame_point(current,x1,y1);end=self.frame_point(current,x2,y2)
        if not self.api.point_is_target(current,*start):raise PcSafetyError('桌面端拖动起点不符合输入条件。')
        self.api.move(*start);self.ensure();self.frame_at=None
        try:
            self.api.button(True)
            for step in range(1,19):
                self._stop_check()
                if self.snapshot()!=current:raise PcSafetyError('拖动期间桌面端窗口位置或尺寸发生变化。')
                point=(round(start[0]+(end[0]-start[0])*step/18),round(start[1]+(end[1]-start[1])*step/18))
                if not self.api.point_is_target(current,*point):raise PcSafetyError('拖动期间桌面端目标失效。')
                self.api.move(*point);time.sleep(seconds/18)
        finally:self.api.button(False)

    def hold(self,x,y,seconds=2.6):
        if not 0<seconds<=4:raise PcSafetyError('桌面端按住时长不符合允许范围。')
        current=self.ensure();point=self.frame_point(current,x,y)
        if not self.api.point_is_target(current,*point):raise PcSafetyError('桌面端按住目标被遮挡。')
        self.api.move(*point);self.ensure()
        if not self.api.point_is_target(current,*point):raise PcSafetyError('桌面端按住目标已变化。')
        try:
            self.api.button(True)
            end=self.clock()+seconds
            while self.clock()<end:
                self.ensure()
                query=getattr(type(self.api),'input_block_reason',None)
                reason=query(self.api,current) if query else ''
                if reason:raise InputBusy(reason)
                if not self.api.point_is_target(current,*point):raise PcSafetyError('按住期间桌面端目标失效。')
                time.sleep(.05)
        finally:
            self.api.button(False);self.frame_at=None

class Win32Api:
    """Foreground screen-copy backend; no PostMessage, hooks or game-memory access."""
    def __init__(self):
        if os.name!='nt':raise PcSafetyError('实验性 STOVE 桌面端适配仅可在 Windows 上运行。')
        import ctypes as c
        from ctypes import wintypes as w
        self.c=c;self.w=w
        self.u=c.WinDLL('user32',use_last_error=True);self.g=c.WinDLL('gdi32',use_last_error=True);self.k=c.WinDLL('kernel32',use_last_error=True)
        self.CB=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        signatures=[
            (self.u,'EnumWindows',[self.CB,w.LPARAM],w.BOOL),
            (self.u,'GetForegroundWindow',[],w.HWND),
            (self.u,'GetWindowThreadProcessId',[w.HWND,c.POINTER(w.DWORD)],w.DWORD),
            (self.u,'GetWindowTextW',[w.HWND,w.LPWSTR,c.c_int],c.c_int),
            (self.u,'GetClientRect',[w.HWND,c.POINTER(w.RECT)],w.BOOL),
            (self.u,'GetWindowRect',[w.HWND,c.POINTER(w.RECT)],w.BOOL),
            (self.u,'ClientToScreen',[w.HWND,c.POINTER(w.POINT)],w.BOOL),
            (self.u,'IsWindowVisible',[w.HWND],w.BOOL),(self.u,'IsIconic',[w.HWND],w.BOOL),
            (self.u,'GetAncestor',[w.HWND,w.UINT],w.HWND),
            (self.u,'WindowFromPoint',[w.POINT],w.HWND),
            (self.u,'GetDpiForWindow',[w.HWND],w.UINT),
            (self.u,'SetThreadDpiAwarenessContext',[c.c_void_p],c.c_void_p),
            (self.u,'GetDC',[w.HWND],w.HDC),(self.u,'ReleaseDC',[w.HWND,w.HDC],c.c_int),
            (self.u,'SetCursorPos',[c.c_int,c.c_int],w.BOOL),
            (self.u,'GetCursorPos',[c.POINTER(w.POINT)],w.BOOL),
            (self.u,'GetAsyncKeyState',[c.c_int],c.c_short),
            (self.u,'GetSystemMetrics',[c.c_int],c.c_int),
            (self.k,'OpenProcess',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
            (self.k,'QueryFullProcessImageNameW',[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)],w.BOOL),
            (self.k,'GetProcessTimes',[w.HANDLE,c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME)],w.BOOL),
            (self.k,'CloseHandle',[w.HANDLE],w.BOOL),
            (self.g,'CreateCompatibleDC',[w.HDC],w.HDC),
            (self.g,'CreateCompatibleBitmap',[w.HDC,c.c_int,c.c_int],w.HBITMAP),
            (self.g,'SelectObject',[w.HDC,w.HGDIOBJ],w.HGDIOBJ),
            (self.g,'DeleteObject',[w.HGDIOBJ],w.BOOL),(self.g,'DeleteDC',[w.HDC],w.BOOL),
            (self.g,'BitBlt',[w.HDC,c.c_int,c.c_int,c.c_int,c.c_int,w.HDC,c.c_int,c.c_int,w.DWORD],w.BOOL),
            (self.g,'GetDIBits',[w.HDC,w.HBITMAP,w.UINT,w.UINT,c.c_void_p,c.c_void_p,w.UINT],c.c_int),
        ]
        for lib,name,args,result in signatures:
            fn=getattr(lib,name);fn.argtypes=args;fn.restype=result
        ulong_ptr=c.c_size_t
        class Mouse(c.Structure):_fields_=[('dx',w.LONG),('dy',w.LONG),('mouseData',w.DWORD),('flags',w.DWORD),('time',w.DWORD),('extra',ulong_ptr)]
        class Key(c.Structure):_fields_=[('vk',w.WORD),('scan',w.WORD),('flags',w.DWORD),('time',w.DWORD),('extra',ulong_ptr)]
        class Hardware(c.Structure):_fields_=[('msg',w.DWORD),('low',w.WORD),('high',w.WORD)]
        class Data(c.Union):_fields_=[('mi',Mouse),('ki',Key),('hi',Hardware)]
        class Input(c.Structure):_fields_=[('type',w.DWORD),('data',Data)]
        self.Mouse=Mouse;self.Key=Key;self.Input=Input
        self.u.SendInput.argtypes=[w.UINT,c.POINTER(Input),c.c_int];self.u.SendInput.restype=w.UINT

    @contextmanager
    def dpi(self):
        old=self.u.SetThreadDpiAwarenessContext(self.c.c_void_p(-4))
        if not old:raise PcSafetyError('无法建立适配各显示器缩放比例的坐标系。')
        try:yield
        finally:self.u.SetThreadDpiAwarenessContext(old)

    def _windows(self):
        result=[]
        @self.CB
        def callback(hwnd,_):result.append(hwnd);return True
        if not self.u.EnumWindows(callback,0):raise PcSafetyError('无法枚举桌面端窗口。')
        return result

    def _process(self,pid):
        c,w=self.c,self.w;h=self.k.OpenProcess(0x1000,False,pid)
        if not h:return None
        try:
            buf=c.create_unicode_buffer(32768);size=w.DWORD(len(buf));times=[w.FILETIME() for _ in range(4)]
            if not self.k.QueryFullProcessImageNameW(h,0,buf,c.byref(size)):return None
            if not self.k.GetProcessTimes(h,*[c.byref(t) for t in times]):return None
            return buf.value,(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
        finally:self.k.CloseHandle(h)

    def windows(self,exe,title):
        # Empty path is discovery-only; returned identity is pinned before input.
        path=os.path.normcase(os.path.abspath(exe)) if exe else None
        if path and Path(path).name.lower()!='epicseven.exe':raise PcSafetyError('仅允许选择游戏进程 EpicSeven.exe。')
        c,w=self.c,self.w;result=[]
        with self.dpi():
            for hwnd in self._windows():
                if not self.u.IsWindowVisible(hwnd) or self.u.IsIconic(hwnd):continue
                buf=c.create_unicode_buffer(1024);self.u.GetWindowTextW(hwnd,buf,len(buf))
                if buf.value!=title:continue
                pid=w.DWORD();self.u.GetWindowThreadProcessId(hwnd,c.byref(pid));p=self._process(pid.value)
                if not p or Path(p[0]).name.lower()!='epicseven.exe':continue
                if path and os.path.normcase(os.path.abspath(p[0]))!=path:continue
                r=w.RECT();point=w.POINT(0,0)
                if not self.u.GetClientRect(hwnd,c.byref(r)) or not self.u.ClientToScreen(hwnd,c.byref(point)):continue
                result.append(WindowSnapshot(int(hwnd),pid.value,p[0],p[1],point.x,point.y,r.right,r.bottom,self.u.GetDpiForWindow(hwnd)))
        return result

    def ready(self,s):
        c,w=self.c,self.w
        with self.dpi():
            if self.u.GetForegroundWindow()!=s.hwnd or self.u.IsIconic(s.hwnd):return False
            vx,vy,vw,vh=[self.u.GetSystemMetrics(i) for i in (76,77,78,79)]
            if not (vx<=s.x and vy<=s.y and s.x+s.width<=vx+vw and s.y+s.height<=vy+vh):return False
            found=False
            for hwnd in self._windows():  # EnumWindows returns top-level Z order.
                if hwnd==s.hwnd:found=True;break
                if not self.u.IsWindowVisible(hwnd) or self.u.IsIconic(hwnd):continue
                r=w.RECT()
                if not self.u.GetWindowRect(hwnd,c.byref(r)):return False
                if r.left<s.x+s.width and r.right>s.x and r.top<s.y+s.height and r.bottom>s.y:return False
            return found

    def point_is_target(self,s,x,y):
        with self.dpi():return self.u.GetAncestor(self.u.WindowFromPoint(self.w.POINT(x,y)),2)==s.hwnd

    def capture(self,s):
        c,w=self.c,self.w
        class Header(c.Structure):_fields_=[('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),('bits',w.WORD),('compression',w.DWORD),('image_size',w.DWORD),('xppm',w.LONG),('yppm',w.LONG),('used',w.DWORD),('important',w.DWORD)]
        class Info(c.Structure):_fields_=[('header',Header),('colors',w.DWORD*3)]
        with self.dpi():
            screen=self.u.GetDC(None);dc=None;bitmap=None;old=None
            try:
                if not screen:raise PcSafetyError('无法获取屏幕设备上下文。')
                dc=self.g.CreateCompatibleDC(screen);bitmap=self.g.CreateCompatibleBitmap(screen,s.width,s.height)
                if not dc or not bitmap:raise PcSafetyError('无法创建桌面端截图画布。')
                old=self.g.SelectObject(dc,bitmap)
                if not old or old==c.c_void_p(-1).value:raise PcSafetyError('无法选择桌面端截图位图。')
                if not self.g.BitBlt(dc,0,0,s.width,s.height,screen,s.x,s.y,0x00CC0020|0x40000000):raise PcSafetyError('桌面端客户区屏幕复制失败。')
                self.g.SelectObject(dc,old);old=None
                info=Info();info.header=Header(c.sizeof(Header),s.width,-s.height,1,32,0,0,0,0,0,0)
                pixels=np.empty((s.height,s.width,4),np.uint8)
                if self.g.GetDIBits(dc,bitmap,0,s.height,pixels.ctypes.data,c.byref(info),0)!=s.height:raise PcSafetyError('桌面端截图不完整。')
                return pixels[:,:,:3].copy()
            finally:
                if old:self.g.SelectObject(dc,old)
                if bitmap:self.g.DeleteObject(bitmap)
                if dc:self.g.DeleteDC(dc)
                if screen:self.u.ReleaseDC(None,screen)

    def move(self,x,y):
        if any(self.u.GetAsyncKeyState(k)&0x8000 for k in (1,2,4,16,17,18,91,92)):
            raise PcSafetyError('检测到用户正按住鼠标或修饰键；已取消桌面端输入。')
        with self.dpi():
            if not self.u.SetCursorPos(x,y):raise PcSafetyError('无法定位桌面端鼠标光标。')

    def _send(self,item):
        if self.u.SendInput(1,self.c.byref(item),self.c.sizeof(item))!=1:raise PcSafetyError('桌面端输入被系统阻止；未尝试绕过权限。')

    def button(self,down):
        item=self.Input();item.type=0;item.data.mi=self.Mouse(0,0,0,2 if down else 4,0,0);self._send(item)

    def escape(self):
        if any(self.u.GetAsyncKeyState(k)&0x8000 for k in (1,2,4,16,17,18,91,92)):
            raise PcSafetyError('检测到用户正按住输入按键；已取消返回操作。')
        item=self.Input();item.type=1;item.data.ki=self.Key(0x1B,0,0,0,0)
        try:self._send(item)
        finally:item.data.ki.flags=2;self._send(item)
