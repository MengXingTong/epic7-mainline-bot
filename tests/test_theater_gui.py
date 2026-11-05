"""Theater task UI only; no discovery or real game worker."""
import unittest
from unittest.mock import patch
try:
    import tkinter as tk
except ImportError:
    tk=None
else:
    from assistant_app import Assistant


@unittest.skipIf(tk is None,'需要独立 Tk 界面运行库')
class TheaterGuiTests(unittest.TestCase):
    def test_task_roundtrip_experimental_warning_and_no_count_limit(self):
        with patch('assistant_app.load_settings',return_value={'task':'theater','mumu':{},'data_dir':''}):
            root=tk.Tk()
            try:
                app=Assistant(root,ui_check=True)
                self.assertEqual(app.current_settings()['task'],'theater')
                self.assertIn('实验性',app.task.get());self.assertIn('一张剧场门票',app.note.get())
                self.assertEqual(app.wins_caption.cget('text'),'本次观览')
                self.assertIsNone(app.process);self.assertFalse(hasattr(app,'limit_box'))
            finally:root.destroy()

@unittest.skipIf(tk is None,'需要独立 Tk 界面运行库')
class TheaterSameRunReloadGuiTests(unittest.TestCase):
    def exercise(self,metadata_error=False):
        import sys
        from unittest.mock import Mock
        with patch('assistant_app.load_settings',return_value={'task':'theater','client':'auto','mumu':{},'data_dir':''}):
            root=tk.Tk()
            try:
                app=Assistant(root,ui_check=True);app.ui_check=False
                request=dict(run_id='a'*32,run_dir='original-run-directory',
                    settings=dict(task='theater',client='auto',mumu={},data_dir='',worker_python=sys.executable),
                    target=dict(client='pc',label='original-target'))
                policy_error=ValueError('reload metadata changed') if metadata_error else None
                with patch('assistant_config.load_theater_resume_request',return_value=request,side_effect=policy_error), \
                        patch.object(app,'command') as command, \
                        patch.object(app,'launch_worker') as launch, \
                        patch.object(app,'start') as new_start:
                    app.resume_existing(request['run_id'])
                    new_start.assert_not_called()
                    if metadata_error:
                        command.assert_not_called();launch.assert_not_called()
                        self.assertEqual(app.mode,'blocked')
                    else:
                        command.assert_called_once_with('run');launch.assert_called_once_with(request)
                        self.assertEqual(app.run_id,request['run_id'])
                        self.assertEqual(str(app.run_dir),request['run_dir'])
                        self.assertEqual(app.targets,[request['target']])
            finally:root.destroy()

    def test_explicit_reload_uses_only_original_request_and_run(self):self.exercise()
    def test_invalid_reload_metadata_blocks_without_fresh_start_or_control_write(self):self.exercise(True)

    def test_delayed_startup_scan_cannot_erase_reload_failure(self):
        with patch('assistant_app.load_settings',return_value={'task':'theater','mumu':{},'data_dir':''}):
            root=tk.Tk()
            try:
                app=Assistant(root,ui_check=True);app.mode='blocked';app.status.set('reload failed')
                with patch.object(app,'scan') as scan:
                    app.initial_scan();scan.assert_not_called()
                self.assertEqual(app.mode,'blocked');self.assertEqual(app.status.get(),'reload failed')
            finally:root.destroy()

    def test_normal_idle_startup_still_scans(self):
        with patch('assistant_app.load_settings',return_value={'task':'theater','mumu':{},'data_dir':''}):
            root=tk.Tk()
            try:
                app=Assistant(root,ui_check=True)
                with patch.object(app,'scan') as scan:
                    app.initial_scan();scan.assert_called_once_with()
            finally:root.destroy()
