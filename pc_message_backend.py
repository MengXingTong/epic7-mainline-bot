"""Opt-in window-message transport; no focus theft, cursor movement or SendInput.
Validated only on the local EpicSeven GLFW30 client in restored-window mode.
API success is delivery, not game acceptance: planners must verify the next frame.
"""
from __future__ import annotations
import math,time
import numpy as np
from pc_backend import Win32Api, PcSafetyError, InputBusy, InputDeliveryError
from pc_message_probe import MessageProbe, ProbeError

class CaptureUnavailable(PcSafetyError):
    """A transient missing/blank frame; NEVER authorizes input or target changes."""

class MessageWin32Api(Win32Api):
    background = True
    def __init__(self):
        super().__init__()
        self.target=None;self.pending=None;self.down=False;self.last_unready_reason=''

    def ready(self,s):
        self.last_unready_reason=''
        if self.u.IsIconic(s.hwnd) or not self.u.IsWindowVisible(s.hwnd):
            self.last_unready_reason='游戏窗口已最小化或不可见';return False
        p=MessageProbe(s.hwnd,s.pid)
        try:q=p.inspect()
        except RuntimeError as exc:self.last_unready_reason=str(exc);return False
        if q.class_name!='GLFW30':
            self.last_unready_reason='窗口类型不在已验证范围内';return False
        if (q.width,q.height)!=(s.width,s.height):
            self.last_unready_reason='客户区尺寸发生变化';return False
        rows=self.windows(s.exe,q.title)
        if len(rows)!=1 or rows[0]!=s:
            self.last_unready_reason='窗口重新核验不一致（实例、位置、尺寸或显示比例）';return False
        if self.target and self.target.identity()!=s.identity():
            self.last_unready_reason='已绑定的窗口或进程身份发生变化，请停止并重选实例';return False
        self.target=s
        return True

    def capture(self,s):
        if not self.ready(s):raise PcSafetyError('后台窗口核验未通过：'+self.last_unready_reason+'。')
        try:image,info=MessageProbe(s.hwnd,s.pid).capture()
        except ProbeError as exc:raise PcSafetyError('后台截图核验失败：'+str(exc)) from exc
        if not info['ok']:raise CaptureUnavailable('后台窗口截图未返回画面；不会回退到屏幕复制。')
        pixels=np.array(image)[:,:,::-1].copy()
        if float(pixels.std())<2:raise CaptureUnavailable('后台截图为空白；未发送输入。')
        if not self.ready(s):raise PcSafetyError('截图后窗口核验未通过：'+self.last_unready_reason+'。')
        return pixels

    def input_block_reason(self,s):
        # Read-only arbitration. Occluding apps own their own mouse; do not
        # pause just because their screen rectangle overlaps the game.
        with self.dpi():
            point=self.w.POINT()
            if not self.u.GetCursorPos(self.c.byref(point)):
                return '当前桌面鼠标状态暂不可读，等待桌面可用后自动继续。'
            if any(self.u.GetAsyncKeyState(key)&0x8000 for key in (1,2,4,5,6,0x10,0x11,0x12)):
                return '检测到鼠标按键或修饰键按住，松开后自动继续。'
            if s.x<=point.x<s.x+s.width and s.y<=point.y<s.y+s.height:
                hwnd=self.u.WindowFromPoint(point)
                if self.u.GetAncestor(hwnd,2)==s.hwnd:
                    return '鼠标位于游戏客户区，移出后自动继续；不会移动你的鼠标。'
        return ''

    def _input_available(self):
        if self.target is None:raise PcSafetyError('尚未锁定后台输入目标。')
        reason=self.input_block_reason(self.target)
        if reason:raise InputBusy(reason)

    def point_is_target(self,s,x,y):
        return self.ready(s) and s.x<=x<s.x+s.width and s.y<=y<s.y+s.height

    def _post(self,msg,wp,lp,release=False):
        if self.target is None:raise PcSafetyError('尚未锁定后台输入目标。')
        s=self.target
        # Release the paired button on the original HWND only, even after resize.
        if release:
            try:q=MessageProbe(s.hwnd,s.pid).inspect()
            except RuntimeError:return
        elif not self.ready(s):raise PcSafetyError('发送前窗口核验未通过：'+self.last_unready_reason+'。')
        self.c.set_last_error(0)
        u=MessageProbe(s.hwnd,s.pid).u
        if not u.PostMessageW(s.hwnd,msg,wp,lp):
            raise InputDeliveryError('窗口消息发送失败（系统错误 %s），已暂停等待处理；不回退输入方式，也不绕过权限。'%self.c.get_last_error())

    def move(self,x,y):
        s=self.target
        if s is None:raise PcSafetyError('尚未锁定后台输入目标。')
        if not self.ready(s):raise PcSafetyError('定位前窗口核验未通过：'+self.last_unready_reason+'。')
        if not (s.x<=x<s.x+s.width and s.y<=y<s.y+s.height):raise PcSafetyError('后台输入位置超出已锁定客户区。')
        if self.down:self._input_available()
        self.pending=(int(x-s.x),int(y-s.y))
        if self.down:self._post(0x200,1,self._lp())

    def _lp(self):
        if self.pending is None:raise PcSafetyError('没有经过核实的后台点击位置。')
        x,y=self.pending
        return (y<<16)|(x&0xffff)

    def button(self,down,*,press_seconds=.07):
        if down and (isinstance(press_seconds,bool) or not isinstance(press_seconds,(int,float))
                     or not math.isfinite(press_seconds) or not .01<=press_seconds<=.07):
            raise PcSafetyError('后台点击按下时长必须为10至70毫秒；已拒绝发送。')
        lp=self._lp()
        if down:
            if self.down:raise PcSafetyError('后台鼠标按下与释放不配对，已拒绝操作。')
            self._input_available()
            self._post(0x200,0,lp);self._input_available();self._post(0x201,1,lp);self.down=True
            time.sleep(press_seconds)
        else:
            if self.down:
                try:self._post(0x202,0,lp,release=True)
                finally:self.down=False

    def escape(self):
        # Public key messages only; no WM_ACTIVATE/WM_SETFOCUS spoofing.
        self._input_available()
        self._post(0x100,0x1b,0x00010001)
        try:time.sleep(.07)
        finally:self._post(0x101,0x1b,0xc0010001,release=True)
