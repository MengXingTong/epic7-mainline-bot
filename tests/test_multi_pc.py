"""Multiple same-executable PC windows, fake native APIs only; zero game input."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
from PIL import Image
from assistant_transport import FrameSnapshot
import unittest
from unittest.mock import Mock, patch
from assistant_transport import UnifiedTransport
from pc_backend import PcBackend, PcSafetyError, WindowSnapshot
from pc_message_backend import MessageWin32Api


class MultiPcTests(unittest.TestCase):
    def setUp(self):
        self.a=WindowSnapshot(10,20,'EpicSeven.exe',30,100,200,1600,900)
        self.b=replace(self.a,hwnd=11,pid=21,created=31)
        self.api=Mock()
        self.api.windows.return_value=[self.a,self.b]
        self.api.ready.return_value=True
        self.target=dict(client='pc',hwnd=10,pid=20,created=30,exe='EpicSeven.exe',title='第七史诗')
    def transport(self):
        with patch('pc_message_backend.MessageWin32Api',return_value=self.api):
            return UnifiedTransport({'pc_input':'messages'},self.target)
    def test_unified_transport_pins_selected_window_among_same_exe_and_title(self):
        transport=self.transport()
        self.assertEqual(transport.ensure(),self.a)
        self.api.windows.return_value=[self.b,self.a]
        self.assertEqual(transport.ensure(),self.a)
        self.api.move.assert_not_called();self.api.button.assert_not_called()
    def test_unified_target_disappears_never_switches_to_other(self):
        transport=self.transport()
        self.api.windows.return_value=[self.b]
        with self.assertRaises(PcSafetyError):transport.ensure()
    def test_recycled_selected_hwnd_is_rejected_at_initialization(self):
        self.api.windows.return_value=[replace(self.a,created=999),self.b]
        with self.assertRaises(PcSafetyError):self.transport()
    def test_geometry_change_of_only_selected_window_is_rejected(self):
        transport=self.transport();transport.ensure()
        frame=FrameSnapshot(Image.new('RGB',(1600,900)),self.a,time.monotonic())
        transport.frame=frame
        self.api.windows.return_value=[replace(self.a,x=300),self.b]
        with self.assertRaises(PcSafetyError):transport._fresh(frame)
        self.api.button.assert_not_called()
    def test_mainline_backend_selects_exact_window_identity(self):
        with tempfile.TemporaryDirectory() as d:
            cfg={'game_exe':self.a.exe,'selected_window':self.a.identity(),'authorization_mode':'selected_target','experimental_input_enabled':True}
            backend=PcBackend(cfg,Path(d)/'STOP',api=self.api)
            backend.authorize_selected_target(self.a.identity())
            self.assertEqual(backend.snapshot(),self.a)
            self.api.windows.return_value=[self.b]
            with self.assertRaises(PcSafetyError):backend.snapshot()
            self.api.button.assert_not_called()
    def test_legacy_unselected_mainline_still_rejects_ambiguity(self):
        with tempfile.TemporaryDirectory() as d:
            backend=PcBackend({'game_exe':self.a.exe},Path(d)/'STOP',api=self.api)
            with self.assertRaises(PcSafetyError):backend.snapshot()
    def test_message_ready_ignores_other_windows_but_checks_selected_geometry(self):
        api=MessageWin32Api.__new__(MessageWin32Api)
        api.u=Mock();api.u.IsIconic.return_value=False;api.u.IsWindowVisible.return_value=True
        api.windows=Mock(return_value=[self.b,self.a]);api.target=None
        probe=Mock();probe.inspect.return_value=SimpleNamespace(class_name='GLFW30',width=1600,height=900,title='第七史诗')
        with patch('pc_message_backend.MessageProbe',return_value=probe):
            self.assertTrue(api.ready(self.a))
            api.windows.return_value=[self.b,replace(self.a,dpi=120)]
            self.assertFalse(api.ready(self.a))
        api.u.PostMessageW.assert_not_called()
