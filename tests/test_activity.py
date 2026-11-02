import unittest
from assistant_status import activity

class ActivityTests(unittest.TestCase):
    def test_idle_is_not_running(self):
        self.assertIn('没有任务',activity('idle').title)
        self.assertFalse(activity('idle').moving)
    def test_scanning_is_not_gameplay(self):
        self.assertIn('尚未启动',activity('scanning').title)
    def test_preflight_not_reported_as_stage_running(self):
        self.assertIn('尚未进入关卡',activity('checking',alive=True).title)
    def test_observation_is_explicit_even_after_resume(self):
        for mode in ('observe','run'):
            self.assertIn('不会点击',activity(mode,observe=True,alive=True).title)
    def test_running_has_task_name(self):
        for task,name in (('mainline','剧情关卡'),('abyss','普通深渊'),('saint_3_7','圣女3-7')):
            self.assertIn('正在推进 · '+name,activity('run',task,False,True).title)
    def test_dead_worker_cannot_show_running(self):
        for mode in ('run','observe'):
            self.assertIn('已停止',activity(mode,alive=False).title)
            self.assertFalse(activity(mode,alive=False).moving)
    def test_pause_stop_wait_for_acknowledgement(self):
        for pending,done in (('pausing','paused'),('stopping','stopped')):
            self.assertTrue(activity(pending,alive=True).moving)
            self.assertFalse(activity(done,alive=True).moving)
    def test_completed_is_not_running(self):
        self.assertIn('结束',activity('done',alive=True).title)
        self.assertFalse(activity('done',alive=True).moving)
    def test_unknown_is_not_running(self):
        self.assertIn('状态未知',activity('new').title)
