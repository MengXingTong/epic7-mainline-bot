"""Waiting-input GUI state with a fake worker; never launch a worker or game input."""
import time
import unittest
from unittest.mock import Mock, patch
try:
    import tkinter as tk
except ImportError:
    tk=None
else:
    from assistant_app import Assistant


@unittest.skipIf(tk is None,'GUI runtime required')
class InputUxGuiTests(unittest.TestCase):
    def setUp(self):
        prefs={'client':'auto','task':'abyss','pc_input':'messages','observe':False,'mumu':{},'data_dir':''}
        self.prefs=patch('assistant_app.load_settings',return_value=prefs);self.prefs.start()
        self.root=tk.Tk();self.app=Assistant(self.root,ui_check=True);self.app.command=Mock()
        self.app.run_id='test';self.app.process=Mock(pid=123);self.app.process.poll.return_value=None
        self.app.mode='waiting_input';self.app.update_buttons()
    def tearDown(self):self.root.destroy();self.prefs.stop()

    def test_scene_wait_keeps_controls_readable_and_pause_stop_available(self):
        self.app.mode='waiting_scene';self.app.update_buttons()
        self.assertEqual(self.app.start_button.cget('text'),'核对画面中…')
        self.assertEqual(self.app.start_button.cget('state'),'disabled')
        self.assertEqual(self.app.start_button.cget('disabledforeground'),'white')
        self.assertEqual(self.app.start_button.cget('activeforeground'),'white')
        self.assertEqual(self.app.pause_button.cget('state'),'normal')
        self.assertEqual(self.app.stop_button.cget('state'),'normal')
    def event(self,mode):
        self.app.events.put(('worker',dict(kind='status',run_id='test',mode=mode,
                                          status='鼠标移出后自动继续',scene='准备战斗',wins=0)))
        self.app.pump()
    def test_input_wait_is_not_failure_and_still_allows_pause_stop(self):
        self.assertIn('自动继续',self.app.activity_title.cget('text'))
        self.assertNotIn('未运行',self.app.activity_title.cget('text'))
        self.assertEqual(self.app.start_button.cget('text'),'等待输入空闲…')
        self.assertEqual(self.app.start_button.cget('state'),'disabled')
        self.assertEqual(self.app.pause_button.cget('state'),'normal')
        self.assertEqual(self.app.stop_button.cget('state'),'normal')
        self.assertIn('不需要重新开始',self.app.activity_meta.cget('text'))
    def test_pause_during_input_wait_requires_ack_and_does_not_resume_on_old_status(self):
        self.app.pause();self.event('waiting_input')
        self.assertEqual(self.app.mode,'pausing')
        self.event('paused');self.assertEqual(self.app.mode,'paused')
        self.assertEqual(self.app.start_button.cget('text'),'继续推进')
    def test_stop_during_input_wait_cannot_be_overwritten_by_automatic_resume(self):
        self.app.stop();self.event('run')
        self.assertEqual(self.app.mode,'stopping')
        self.app.command.assert_called_once_with('stop')
    def test_wait_heartbeats_prevent_false_unresponsive_termination(self):
        self.app.started=time.monotonic()-100;self.app.last_heartbeat=time.monotonic()-80
        self.event('waiting_input')
        self.app.process.terminate.assert_not_called()
        self.assertEqual(self.app.mode,'waiting_input')
    def test_mouse_leaving_returns_to_running_in_same_worker(self):
        child=self.app.process;self.event('run')
        self.assertIs(self.app.process,child);self.assertEqual(self.app.mode,'run')
        self.assertIn('推进中',self.app.start_button.cget('text'))
