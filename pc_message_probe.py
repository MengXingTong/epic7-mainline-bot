"""Bounded public-Win32 diagnostics; never activates windows or moves the cursor.
This is a developer probe, not a general automation backend. Input is restricted
by the caller to a freshly observed, non-spending navigation control.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import ctypes as c
from ctypes import wintypes as w
import json, time
from pathlib import Path

class ProbeError(RuntimeError): pass

@dataclass(frozen=True)
class WindowIdentity:
    hwnd: int
    pid: int
    title: str
    class_name: str
    width: int
    height: int
    foreground: bool
    minimized: bool

class MessageProbe:
    def __init__(self, hwnd, pid):
        self.hwnd=int(hwnd); self.pid=int(pid)
        self.u=c.WinDLL('user32',use_last_error=True)
        self.g=c.WinDLL('gdi32',use_last_error=True)
        self.cb=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        for lib,name,args,result in [
            (self.u,'IsWindow',[w.HWND],w.BOOL),
            (self.u,'IsIconic',[w.HWND],w.BOOL),
            (self.u,'GetForegroundWindow',[],w.HWND),
            (self.u,'GetWindowThreadProcessId',[w.HWND,c.POINTER(w.DWORD)],w.DWORD),
            (self.u,'GetWindowTextW',[w.HWND,w.LPWSTR,c.c_int],c.c_int),
            (self.u,'GetClassNameW',[w.HWND,w.LPWSTR,c.c_int],c.c_int),
            (self.u,'GetClientRect',[w.HWND,c.POINTER(w.RECT)],w.BOOL),
            (self.u,'EnumChildWindows',[w.HWND,self.cb,w.LPARAM],w.BOOL),
            (self.u,'PostMessageW',[w.HWND,w.UINT,w.WPARAM,w.LPARAM],w.BOOL),
            (self.u,'SendMessageTimeoutW',[w.HWND,w.UINT,w.WPARAM,w.LPARAM,w.UINT,w.UINT,c.POINTER(c.c_size_t)],c.c_size_t),
            (self.u,'GetCursorPos',[c.POINTER(w.POINT)],w.BOOL),
            (self.u,'GetDC',[w.HWND],w.HDC),
            (self.u,'ReleaseDC',[w.HWND,w.HDC],c.c_int),
            (self.u,'PrintWindow',[w.HWND,w.HDC,w.UINT],w.BOOL),
            (self.u,'SetThreadDpiAwarenessContext',[c.c_void_p],c.c_void_p),
            (self.g,'CreateCompatibleDC',[w.HDC],w.HDC),
            (self.g,'CreateCompatibleBitmap',[w.HDC,c.c_int,c.c_int],w.HBITMAP),
            (self.g,'SelectObject',[w.HDC,w.HGDIOBJ],w.HGDIOBJ),
            (self.g,'GetDIBits',[w.HDC,w.HBITMAP,w.UINT,w.UINT,c.c_void_p,c.c_void_p,w.UINT],c.c_int),
            (self.g,'DeleteObject',[w.HGDIOBJ],w.BOOL),
            (self.g,'DeleteDC',[w.HDC],w.BOOL),
        ]:
            f=getattr(lib,name);f.argtypes=args;f.restype=result
        self.u.SetThreadDpiAwarenessContext(c.c_void_p(-4))

    def inspect(self):
        if not self.u.IsWindow(self.hwnd): raise ProbeError('目标窗口已不存在。')
        pid=w.DWORD(); self.u.GetWindowThreadProcessId(self.hwnd,c.byref(pid))
        text=c.create_unicode_buffer(256); cls=c.create_unicode_buffer(256)
        self.u.GetWindowTextW(self.hwnd,text,len(text));self.u.GetClassNameW(self.hwnd,cls,len(cls))
        if pid.value!=self.pid or text.value not in ('\u7b2c\u4e03\u53f2\u8bd7','\u7b2c\u4e03\u53f2\u8a69','Epic Seven'):
            raise ProbeError('目标窗口身份已变化。')
        r=w.RECT()
        if not self.u.GetClientRect(self.hwnd,c.byref(r)):raise ProbeError('无法读取客户区位置和尺寸。')
        return WindowIdentity(self.hwnd,self.pid,text.value,cls.value,r.right,r.bottom,self.u.GetForegroundWindow()==self.hwnd,bool(self.u.IsIconic(self.hwnd)))

    def cursor(self):
        p=w.POINT();self.u.GetCursorPos(c.byref(p));return p.x,p.y

    def children(self):
        rows=[]
        @self.cb
        def cb(hwnd,_):
            cls=c.create_unicode_buffer(128);self.u.GetClassNameW(hwnd,cls,len(cls))
            rows.append({'hwnd':int(hwnd),'class':cls.value});return True
        self.u.EnumChildWindows(self.hwnd,cb,0)
        return rows

    def capture(self):
        """PrintWindow experiment; return image and API outcome, never claim freshness."""
        from PIL import Image
        s=self.inspect()
        if s.minimized or s.width<640 or s.height<360:raise ProbeError('请先还原游戏窗口，再执行诊断。')
        src=self.u.GetDC(self.hwnd);dc=self.g.CreateCompatibleDC(src)
        bitmap=self.g.CreateCompatibleBitmap(src,s.width,s.height)
        if not (src and dc and bitmap):raise ProbeError('无法分配截图资源。')
        old=self.g.SelectObject(dc,bitmap)
        class Header(c.Structure):
            _fields_=[('size',w.DWORD),('width',w.LONG),('height',w.LONG),('planes',w.WORD),('bits',w.WORD),('compression',w.DWORD),('image_size',w.DWORD),('x',w.LONG),('y',w.LONG),('used',w.DWORD),('important',w.DWORD)]
        h=Header(c.sizeof(Header),s.width,-s.height,1,32,0,0,0,0,0,0)
        buf=c.create_string_buffer(s.width*s.height*4)
        try:
            c.set_last_error(0)
            ok=bool(self.u.PrintWindow(self.hwnd,dc,3));error=c.get_last_error()
            self.g.SelectObject(dc,old);old=None
            lines=self.g.GetDIBits(dc,bitmap,0,s.height,buf,c.byref(h),0)
            if lines!=s.height:raise ProbeError('后台窗口截图输出不完整。')
            return Image.frombytes('RGB',(s.width,s.height),buf.raw,'raw','BGRX'),{'ok':ok,'error':error,'identity':asdict(s)}
        finally:
            if old:self.g.SelectObject(dc,old)
            self.g.DeleteObject(bitmap);self.g.DeleteDC(dc);self.u.ReleaseDC(self.hwnd,src)

    def navigation_click(self, method, action, observed_at, observed_identity):
        # Only non-spending Back controls. No generic click API and no entry buttons.
        positions={'clear_return':(.12,.925),'normal_back':(.027,.045)}
        if action not in positions or method not in ('post','send'):raise ProbeError('诊断操作不在允许范围内。')
        if not 0<=time.time()-observed_at<=12:raise ProbeError('诊断画面已过期。')
        before=self.inspect()
        if before!=observed_identity:raise ProbeError('观察后窗口已变化。')
        if before.foreground or before.minimized:raise ProbeError('此诊断要求游戏窗口已还原且处于失焦状态。')
        foreground=self.u.GetForegroundWindow();cursor=self.cursor()
        x,y=positions[action];x=round(x*before.width);y=round(y*before.height)
        lp=(y<<16)|(x&0xffff)
        def emit(msg,wp):
            current=self.inspect()
            if current!=before:raise ProbeError('诊断输入期间目标已变化。')
            c.set_last_error(0)
            if method=='post':ok=self.u.PostMessageW(self.hwnd,msg,wp,lp)
            else:
                result=c.c_size_t()
                ok=self.u.SendMessageTimeoutW(self.hwnd,msg,wp,lp,0x22,250,c.byref(result))
            error=c.get_last_error()
            if not ok:raise ProbeError(f'窗口消息发送失败（方式 {method}，系统错误 {error}）；未尝试提权或绕过权限。')
        emit(0x200,0)
        emit(0x201,1)
        try:time.sleep(.12)
        finally:emit(0x202,0)
        return {'method':method,'action':action,'delivered_to_message_queue_only':True,
                'foreground_unchanged':foreground==self.u.GetForegroundWindow(),
                'cursor_unchanged':cursor==self.cursor(),'identity':asdict(before)}
