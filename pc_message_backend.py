"""Opt-in window-message transport; no focus theft, cursor movement or SendInput.
Validated only on the local EpicSeven GLFW30 client in restored-window mode.
API success is delivery, not game acceptance: planners must verify the next frame.
"""
from __future__ import annotations
import time
import numpy as np
from pc_backend import Win32Api, PcSafetyError
from pc_message_probe import MessageProbe

class CaptureUnavailable(PcSafetyError):
    """A transient missing/blank frame; NEVER authorizes input or target changes."""

class MessageWin32Api(Win32Api):
    background = True
    def __init__(self):
        super().__init__()
        self.target=None;self.pending=None;self.down=False

    def ready(self,s):
        if self.u.IsIconic(s.hwnd) or not self.u.IsWindowVisible(s.hwnd):return False
        p=MessageProbe(s.hwnd,s.pid)
        try:q=p.inspect()
        except RuntimeError:return False
        if q.class_name!='GLFW30' or (q.width,q.height)!=(s.width,s.height):return False
        rows=self.windows(s.exe,q.title)
        if len(rows)!=1 or rows[0]!=s:return False
        if self.target and self.target.identity()!=s.identity():return False
        self.target=s
        return True

    def capture(self,s):
        if not self.ready(s):raise PcSafetyError('Background target changed, minimized or unsupported')
        image,info=MessageProbe(s.hwnd,s.pid).capture()
        if not info['ok']:raise CaptureUnavailable('PrintWindow did not provide a frame; no screen-copy fallback')
        pixels=np.array(image)[:,:,::-1].copy()
        if float(pixels.std())<2:raise CaptureUnavailable('Blank background capture; no input sent')
        if not self.ready(s):raise PcSafetyError('Background geometry changed during capture')
        return pixels

    def point_is_target(self,s,x,y):
        return self.ready(s) and s.x<=x<s.x+s.width and s.y<=y<s.y+s.height

    def _post(self,msg,wp,lp,release=False):
        if self.target is None:raise PcSafetyError('No pinned background target')
        s=self.target
        # Release the paired button on the original HWND only, even after resize.
        if release:
            try:q=MessageProbe(s.hwnd,s.pid).inspect()
            except RuntimeError:return
        elif not self.ready(s):raise PcSafetyError('Background target changed before message')
        self.c.set_last_error(0)
        u=MessageProbe(s.hwnd,s.pid).u
        if not u.PostMessageW(s.hwnd,msg,wp,lp):
            raise PcSafetyError('Window message blocked (Win32 %s); no fallback or privilege bypass'%self.c.get_last_error())

    def move(self,x,y):
        s=self.target
        if s is None or not self.point_is_target(s,x,y):raise PcSafetyError('Background point outside pinned client')
        self.pending=(int(x-s.x),int(y-s.y))
        if self.down:self._post(0x200,1,self._lp())

    def _lp(self):
        if self.pending is None:raise PcSafetyError('No verified background click point')
        x,y=self.pending
        return (y<<16)|(x&0xffff)

    def button(self,down):
        lp=self._lp()
        if down:
            if self.down:raise PcSafetyError('Unpaired background button-down')
            self._post(0x200,0,lp);self._post(0x201,1,lp);self.down=True
            time.sleep(.07)
        else:
            if self.down:
                try:self._post(0x202,0,lp,release=True)
                finally:self.down=False

    def escape(self):
        # Public key messages only; no WM_ACTIVATE/WM_SETFOCUS spoofing.
        self._post(0x100,0x1b,0x00010001)
        try:time.sleep(.07)
        finally:self._post(0x101,0x1b,0xc0010001,release=True)
