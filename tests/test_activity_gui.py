"""GUI-only transitions; faked workers, no process launch and no game input."""
import unittest
from unittest.mock import Mock,patch
try:
    import tkinter as tk
except ImportError:
    tk=None
else:
    from assistant_app import Assistant

@unittest.skipIf(tk is None,'GUI runtime (Tk) required; run this file with GUI Python')
class GuiActivityTests(unittest.TestCase):
    def setUp(self):
        self.prefs=patch('assistant_app.load_settings',return_value={'client':'auto','task':'mainline','pc_input':'messages','limit':3,'observe':True,'mumu':{},'data_dir':''});self.prefs.start()
        self.root=tk.Tk();self.app=Assistant(self.root,ui_check=True);self.app.command=Mock();self.app.run_id='test'
    def tearDown(self):self.root.destroy();self.prefs.stop()
    def worker(self,mode='observe'):
        child=Mock();child.pid=123;child.poll.return_value=None
        self.app.read_only=mode=='observe';self.app.process=child;self.app.mode=mode;self.app.update_buttons();return child
    def event(self,mode,detail='current step'):
        self.app.events.put(('worker',{'kind':'status','run_id':'test','mode':mode,'status':detail}))
        self.app.pump()
    def test_idle_stops_animation_and_disables_pause(self):
        self.assertIn('未启动',self.app.activity_title.cget('text'))
        self.assertEqual(self.app.pause_button.cget('state'),'disabled')
        self.assertEqual(str(self.app.activity_progress.cget('mode')),'determinate')

    def test_saved_client_does_not_override_auto_detection_on_next_launch(self):
        for old_client in ('mumu','pc'):
            with self.subTest(old_client=old_client):
                top=tk.Toplevel(self.root)
                try:
                    with patch('assistant_app.load_settings',return_value={'client':old_client,'task':'abyss','mumu':{},'data_dir':''}):
                        app=Assistant(top,ui_check=True)
                    self.assertEqual(app.client.get(),'自动识别')
                    self.assertEqual(app.task.get(),'普通深渊')
                    app.targets=[dict(client='pc',label='live-pc')];app.filter_targets()
                    self.assertEqual(app.selected_target()['client'],'pc')
                finally:top.destroy()
    def test_live_observer_clearly_labels_button(self):
        self.worker()
        self.assertIn('不会点击',self.app.activity_title.cget('text'))
        self.assertEqual(self.app.start_button.cget('text'),'观察中…')
        self.assertEqual(self.app.start_button.cget('state'),'disabled')
    def test_live_run_and_detail_visible_in_fixed_header(self):
        self.app.read_only=False;self.worker('run');self.event('run','请等待原生战斗结束')
        self.assertIn('正在推进',self.app.activity_title.cget('text'))
        self.assertIn('请等待',self.app.activity_detail.cget('text'))
        self.assertEqual(self.app.start_button.cget('text'),'推进中…')
    def test_result_evidence_wait_is_automatic_and_keeps_pause_stop_available(self):
        self.app.read_only=False;self.worker('run');self.event('waiting_evidence','缺少原节点独立通关勾，持续取图核实')
        self.assertIn('自动推进',self.app.activity_title.cget('text'))
        self.assertEqual(self.app.start_button.cget('text'),'核实结果中…')
        self.assertEqual(self.app.start_button.cget('state'),'disabled')
        self.assertEqual(self.app.pause_button.cget('state'),'normal')
        self.assertEqual(self.app.stop_button.cget('state'),'normal')
        self.app.pause();self.app.command.assert_called_with('pause')

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
    def test_terminal_status_before_process_exit_is_reconciled_without_exit_event(self):
        child=self.worker('run');self.event('stopped')
        self.assertEqual(self.app.start_button.cget('text'),'等待进程退出…')
        child.poll.return_value=0;self.app.pump()
        self.assertIsNone(self.app.process)
        self.assertEqual(self.app.mode,'stopped')
        self.assertEqual(self.app.start_button.cget('text'),'开始推进')
        self.assertEqual(self.app.start_button.cget('state'),'normal')
        self.app.command.assert_not_called()
    def test_early_eof_exit_event_never_unlocks_a_live_writer(self):
        child=self.worker('run');self.event('stopped')
        self.app.events.put(('exit',child.pid));self.app.pump()
        self.assertIs(self.app.process,child)
        self.assertEqual(self.app.start_button.cget('state'),'disabled')
        child.poll.return_value=0;self.app.pump()
        self.assertIsNone(self.app.process)
        self.assertEqual(self.app.start_button.cget('state'),'normal')
    def test_old_exit_event_cannot_detach_a_new_worker(self):
        child=self.worker('run');self.app.events.put(('exit',999));self.app.pump()
        self.assertIs(self.app.process,child)
        self.assertEqual(self.app.mode,'run')

    def test_stale_status_from_old_run_ignored(self):
        self.worker();self.app.events.put(('worker',{'kind':'status','run_id':'old','mode':'run','status':'old'}));self.app.pump()
        self.assertEqual(self.app.mode,'observe')

    def test_user_interface_has_no_observation_or_confirmation_switch(self):
        self.assertFalse(hasattr(self.app,'observe_box'));self.assertFalse(hasattr(self.app,'confirm_box'))
        self.assertFalse(self.app.read_only)
        self.assertFalse(self.app.current_settings()['observe'])
        self.assertEqual(self.app.start_button.cget('text'),'开始推进')
    def test_old_saved_observation_flag_does_not_block_direct_start(self):
        self.app.settings['observe']=True
        self.assertFalse(self.app.current_settings()['observe'])

    def test_start_click_launches_directly_without_confirmation_dialog(self):
        import tempfile,json,sys
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            home=Path(d);self.app.home=home;self.app.base_home=home;self.app.settings.update(worker_python=sys.executable,observe=True)
            target={'client':'pc','label':'test','hwnd':1,'pid':2,'created':3.,'exe':'synthetic-game.exe','title':'synthetic'};self.app.filtered=[target];self.app.instance.set('test')
            child=Mock();child.pid=123;child.poll.return_value=None
            with patch('assistant_app.HOME',home),patch('assistant_app.validate_run',return_value=(home,{})),patch('assistant_portable.save_settings'),patch('assistant_app.subprocess.Popen',return_value=child) as launch,patch('assistant_app.threading.Thread'):
                self.app.start()
            launch.assert_called_once()
            request=json.loads((self.app.run_dir/'request.json').read_text(encoding='utf-8'))
            self.assertFalse(request['settings']['observe']);self.assertTrue(request['user_selected_profile'])
            self.assertNotIn('first_use_consent',request);self.assertNotIn('bind_existing_consent',request)
            self.assertEqual(self.app.start_button.cget('text'),'检查中…')

    def test_noncritical_warning_keeps_running_state_and_clears_on_recovery(self):
        self.worker('run');self.app.read_only=False
        self.app.events.put(('worker',{'kind':'status','run_id':'test','mode':'run','status':'自动战斗中','warning':'状态报告暂时无法更新；关键进度已保存'}))
        self.app.pump();self.root.update_idletasks()
        self.assertEqual(self.app.mode,'run');self.assertIn('正在推进',self.app.activity_title.cget('text'))
        self.assertTrue(self.app.warning_label.winfo_manager());self.assertIn('状态报告',self.app.warning_label.cget('text'))
        self.assertLessEqual(self.app.stop_button.winfo_rooty()+self.app.stop_button.winfo_height(),self.app.workarea[3])
        self.app.events.put(('worker',{'kind':'status','run_id':'test','mode':'run','status':'自动战斗中','warning':''}))
        self.app.pump();self.assertFalse(self.app.warning_label.winfo_manager());self.assertEqual(self.app.mode,'run')

    def test_attention_has_continue_button_and_no_watchdog_kill(self):
        import time
        child=self.worker('run');self.event('attention','装备已满，手动处理后继续');self.app.started=time.monotonic()-100
        self.app.last_heartbeat=time.monotonic()-100;self.app.pump()
        self.assertIn('等待处理',self.app.activity_title.cget('text'))
        self.assertEqual(self.app.start_button.cget('text'),'处理后继续');self.assertEqual(self.app.start_button.cget('state'),'normal')
        child.terminate.assert_not_called();self.app.start();self.app.command.assert_called_with('run')
    def test_stopped_worker_can_start_a_new_run(self):
        child=self.worker('run');self.event('stopped');child.poll.return_value=0;self.app.events.put(('exit',child.pid));self.app.pump()
        self.assertEqual(self.app.start_button.cget('text'),'开始推进');self.assertEqual(self.app.start_button.cget('state'),'normal')
        self.assertEqual(str(self.app.task_box.cget('state')),'readonly')
    def test_interface_has_no_foreground_selector(self):
        self.assertFalse(hasattr(self.app,'input_box'));self.assertEqual(self.app.current_settings()['pc_input'],'messages')

    def test_interface_has_no_count_limit_or_legacy_setting(self):
        self.app.settings['limit']=30
        self.assertFalse(hasattr(self.app,'limit_box'));self.assertFalse(hasattr(self.app,'limit'))
        self.assertIn('不设次数上限',self.app.run_policy.cget('text'))
        self.assertNotIn('limit',self.app.current_settings())

    def test_story_and_saint_modes_share_the_same_task_selector(self):
        from assistant_app import TASKS
        self.assertEqual(TASKS['推进剧情关卡'],'mainline');self.assertEqual(TASKS['圣女3-7'],'saint_3_7')
        self.app.task.set('圣女3-7');self.assertEqual(self.app.current_settings()['task'],'saint_3_7')
        self.app.task.set('推进剧情关卡');self.assertEqual(self.app.current_settings()['task'],'mainline')
    def test_maintenance_restart_requires_current_run_identity(self):
        self.worker('run');self.app.start=Mock();self.app.stop=Mock()
        request={'command_id':'unmatched','expected_run_id':'old','task':'saint_3_7','action':'restart'}
        with patch('assistant_app.read_json',return_value=request):self.app.pump()
        self.app.stop.assert_not_called();self.app.start.assert_not_called();self.assertIsNone(self.app.pending_restart)
    def test_maintenance_restart_waits_for_worker_exit(self):
        child=self.worker('run');self.app.start=Mock();self.app.stop=Mock()
        request={'command_id':'maintenance','expected_run_id':'test','task':'saint_3_7','action':'restart'}
        with patch('assistant_app.read_json',return_value=request):self.app.pump()
        self.app.stop.assert_called_once();self.app.start.assert_not_called()
        child.poll.return_value=0
        with patch('assistant_app.read_json',return_value=request):self.app.pump()
        self.app.start.assert_called_once();self.assertEqual(self.app.task.get(),'圣女3-7');self.assertIsNone(self.app.pending_restart)

    def test_farming_counter_shows_confirmed_successes_not_current_battle(self):
        self.worker('run');self.app.read_only=False
        self.app.events.put(('worker',{'kind':'status','run_id':'test','mode':'run','status':'本轮自动战斗中','scene':'battle','stage':'3-7','story_mode':'farm','farm_runs':2}))
        self.app.pump();self.assertEqual(self.app.scene.get(),'3-7 · 已成功 2 次');self.assertEqual(self.app.mode,'run')

    def test_raw_scene_code_is_displayed_in_chinese(self):
        self.worker('run')
        self.app.events.put(('worker', {'kind': 'status', 'run_id': 'test', 'mode': 'run',
                                       'status': '正在推进', 'scene': 'battle'}))
        self.app.pump()
        self.assertEqual(self.app.scene.get(), '自动战斗中')

    def test_header_uses_chinese_product_name(self):
        def labels(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Label):
                    yield child.cget('text')
                yield from labels(child)
        self.assertIn('第七史诗 / 统一推进助手', list(labels(self.root)))
