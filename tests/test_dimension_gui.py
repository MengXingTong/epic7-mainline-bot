"""Dimension UI integration; fake workers and no client discovery/input."""
import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
try:
    import tkinter as tk
except ImportError:tk=None
else:
    from assistant_app import Assistant,TASKS

@unittest.skipIf(tk is None,'需要独立 Tk 界面运行库')
class DimensionGuiTests(unittest.TestCase):
    def setUp(self):
        self.prefs=patch('assistant_app.load_settings',return_value={'client':'auto','task':'dimension','pc_input':'messages','mumu':{},'data_dir':''});self.prefs.start()
        self.root=tk.Tk();self.app=Assistant(self.root,ui_check=True)
    def tearDown(self):self.root.destroy();self.prefs.stop()
    def test_mode_roundtrips_and_experimental_limits_visible(self):
        self.assertEqual(self.app.current_settings()['task'],'dimension')
        self.assertIn('实验性',self.app.task.get());self.assertIn('路线、抉择、招募与通关待实测',self.app.note.get())
    def test_selection_does_not_start_or_add_count_limit(self):
        self.assertFalse(self.app.read_only);self.assertFalse(hasattr(self.app,'limit_box'))
        self.assertIsNone(self.app.process);self.assertEqual(self.app.mode,'idle')
