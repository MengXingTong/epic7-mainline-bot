"""GUI configuration only: no discovery or worker starts."""
import unittest
from unittest.mock import patch
try:
    import tkinter as tk
except ImportError:tk=None
else:
    from assistant_app import Assistant

@unittest.skipIf(tk is None,'需要独立 Tk 界面运行库')
class PenguinGuiTests(unittest.TestCase):
    def test_count_required_only_for_penguin_roundtrip_and_locked(self):
        with patch('assistant_app.load_settings',return_value={'task':'penguin','mumu':{},'data_dir':''}):
            root=tk.Tk()
            try:
                a=Assistant(root,ui_check=True)
                self.assertIn('实验性',a.task.get());self.assertEqual(a.wins_caption.cget('text'),'已购企鹅')
                self.assertEqual(a.start_button.cget('text'),'开始购买')
                self.assertIn('总只数',a.note.get());self.assertEqual(a.penguin_box.winfo_manager(),'grid')
                with self.assertRaises(ValueError):a.current_settings()
                a.penguin_quantity.set('51');self.assertEqual(a.current_settings()['penguin_quantity'],51)
                a.lock_choices(True);self.assertIn('disabled',a.penguin_box.state())
                a.lock_choices(False);self.assertNotIn('disabled',a.penguin_box.state())
                a.task.set('推进剧情关卡');a.update_note()
                self.assertEqual(a.penguin_box.winfo_manager(),'');self.assertNotIn('limit',a.current_settings())
                self.assertIn('不设次数上限',a.run_policy.cget('text'))
                self.assertIsNone(a.process)
            finally:root.destroy()

    def test_maintenance_restart_cannot_start_another_purchase_order(self):
        from unittest.mock import Mock
        with patch('assistant_app.load_settings',return_value={'task':'penguin','mumu':{},'data_dir':'','penguin_quantity':1}):
            root=tk.Tk()
            try:
                a=Assistant(root,ui_check=True);a.run_id='old';a.stop=Mock();a.start=Mock()
                command=dict(command_id='new',expected_run_id='old',task='penguin',action='restart')
                with patch('assistant_app.read_json',return_value=command):a.pump()
                a.stop.assert_not_called();a.start.assert_not_called();self.assertIsNone(a.pending_restart)
            finally:root.destroy()

class PenguinValidationTests(unittest.TestCase):
    def test_pc_experimental_only_count_and_observe_safety(self):
        from assistant_config import validate_run
        settings=dict(task='penguin',penguin_quantity=10,pc_input='messages',data_dir='')
        with patch('assistant_portable.registered_root',return_value=None):
            validate_run(settings,{'client':'pc'})
            for bad,target in ((dict(settings,penguin_quantity=''),{'client':'pc'}),
                    (settings,{'client':'mumu'}),(dict(settings,observe=True),{'client':'pc'}),
                    (dict(settings,pc_input='foreground'),{'client':'pc'})):
                with self.assertRaises(ValueError):validate_run(bad,target)

    def test_cli_restart_does_not_reuse_old_order(self):
        import tempfile
        from pathlib import Path
        import assistant_control
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);folder=home/'runs'/'old';folder.mkdir(parents=True)
            from assistant_config import atomic_json
            atomic_json(home/'active-run.json',dict(run_id='old',run_dir=str(folder)))
            atomic_json(folder/'status.json',dict(run_id='old',mode='done'))
            atomic_json(folder/'request.json',dict(settings=dict(task='penguin',penguin_quantity=50)))
            with patch.object(assistant_control,'HOME',home),patch('sys.argv',['assistant_control.py','restart']):
                with self.assertRaises(ValueError):assistant_control.main()
            self.assertFalse((home/'gui-command.json').exists())
