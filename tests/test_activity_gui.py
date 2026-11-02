"""GUI-only transitions; faked workers, no process launch and no game input."""
import unittest
from unittest.mock import Mock,patch
try:
    import tkinter as tk
    from assistant_app import Assistant
except ImportError:
    tk=None

@unittest.skipIf(tk is None,'GUI runtime (Tk) required; run this file with GUI Python')
class GuiActivityTests(unittest.TestCase):
    def setUp(self):
        self.prefs=patch('assistant_app.load_settings',return_value={'client':'auto','task':'mainline','pc_input':'messages','limit':3,'observe':True,'mumu':{},'data_dir':''});self.prefs.start()
        self.root=tk.Tk();self.app=Assistant(self.root,ui_check=True);self.app.command=Mock();self.app.run_id='test'
    def tearDown(self):self.root.destroy();self.prefs.stop()
    def worker(self,mode='observe'):
        child=Mock();child.pid=123;child.poll.return_value=None
        self.app.process=child;self.app.mode=mode;self.app.update_buttons();return child
    def event(self,mode,detail='current step'):
        self.app.events.put(('worker',{'kind':'status','run_id':'test','mode':mode,'status':detail}))
        self.app.pump()
    def test_idle_stops_animation_and_disables_pause(self):
        self.assertIn('未启动',self.app.activity_title.cget('text'))
        self.assertEqual(self.app.pause_button.cget('state'),'disabled')
        self.assertEqual(str(self.app.activity_progress.cget('mode')),'determinate')
    def test_live_observer_clearly_labels_button(self):
        self.worker()
        self.assertIn('不会点击',self.app.activity_title.cget('text'))
        self.assertEqual(self.app.start_button.cget('text'),'观察中…')
        self.assertEqual(self.app.start_button.cget('state'),'disabled')
    def test_live_run_and_detail_visible_in_fixed_header(self):
        self.app.observe.set(False);self.worker('run');self.event('run','请等待原生战斗结束')
        self.assertIn('正在推进',self.app.activity_title.cget('text'))
        self.assertIn('请等待',self.app.activity_detail.cget('text'))
        self.assertEqual(self.app.start_button.cget('text'),'推进中…')
    def test_pause_request_waits_for_ack(self):
        self.worker();self.app.pause()
        self.assertEqual(self.app.mode,'pausing');self.assertIn('正在暂停',self.app.activity_title.cget('text'))
        self.event('observe');self.assertEqual(self.app.mode,'pausing')
        self.event('paused');self.assertIn('已暂停',self.app.activity_title.cget('text'))
        self.assertEqual(self.app.start_button.cget('text'),'继续观察')
    def test_stop_request_waits_for_ack(self):
        self.worker();self.app.stop();self.event('observe')
        self.assertEqual(self.app.mode,'stopping')
        self.event('stopped');self.assertIn('已停止',self.app.activity_title.cget('text'))
    def test_dead_worker_not_shown_running(self):
        child=self.worker();child.poll.return_value=0;self.app.events.put(('exit',123));self.app.pump()
        self.assertEqual(self.app.mode,'blocked');self.assertNotIn('正在观察',self.app.activity_title.cget('text'))
    def test_stale_status_from_old_run_ignored(self):
        self.worker();self.app.events.put(('worker',{'kind':'status','run_id':'old','mode':'run','status':'old'}));self.app.pump()
        self.assertEqual(self.app.mode,'observe')
