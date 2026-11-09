"""Hidden Tk binding tests: no discovery subprocess, game window or input."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import tkinter as tk
except ImportError:
    tk = None
else:
    from assistant_app import Assistant


def pc(number=1, **changes):
    return dict(dict(client='pc', hwnd=number, pid=100 + number, created=1000 + number,
                     exe='EpicSeven.exe', title='第七史诗', label=f'PC {number}'), **changes)


@unittest.skipIf(tk is None, 'Tk runtime required; all test windows stay hidden')
class HiddenSelectionGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        home = Path(self.temp.name)
        with patch('assistant_app.load_settings', return_value=dict(client='auto', task='mainline', mumu={}, data_dir='')):
            self.app = Assistant(self.root, ui_check=True, home=home, base_home=home)

    def choose(self, index):
        self.app.target_box.current(index)
        self.app.target_box.event_generate('<<ComboboxSelected>>')
        self.root.update_idletasks()

    def test_initial_and_empty_states_disable_start(self):
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.app.filter_targets()
        self.assertIn('未检测到', self.app.status.get())
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')

    def test_virtual_selection_event_enables_start_and_updates_structured_target(self):
        self.app.targets = [pc(), pc(2)]
        self.app.filter_targets()
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.choose(1)
        self.assertEqual(self.app.selected_target(), pc(2))
        self.assertEqual(self.app.start_button.cget('state'), 'normal')

    def test_refresh_keeps_manual_choice_and_updates_display_name(self):
        self.app.targets = [pc(), pc(2)]
        self.app.filter_targets()
        self.choose(1)
        updated = pc(2, label='PC 2 resized', width=1920)
        self.app.targets = [updated, pc()]
        self.app.filter_targets()
        self.assertEqual(self.app.selected_target(), updated)
        self.assertEqual(self.app.instance.get(), 'PC 2 resized')
        self.assertEqual(self.app.start_button.cget('state'), 'normal')

    def test_duplicate_names_are_selectable_by_distinct_combobox_entries(self):
        self.app.targets = [pc(label='same'), pc(2, label='same')]
        self.app.filter_targets()
        self.assertEqual(len(set(self.app.target_box.cget('values'))), 2)
        self.choose(1)
        self.assertEqual(self.app.selected_target()['hwnd'], 2)
        self.app.targets.reverse()
        self.app.filter_targets()
        self.assertEqual(self.app.selected_target()['hwnd'], 2)

    def test_missing_original_requires_explicit_selection_not_auto_fallback(self):
        self.app.targets = [pc()]
        self.app.filter_targets()
        self.app.targets = [pc(2)]
        self.app.filter_targets()
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.assertIn('原绑定实例', self.app.status.get())
        self.choose(0)
        self.assertEqual(self.app.selected_target(), pc(2))
        self.assertEqual(self.app.start_button.cget('state'), 'normal')

    def test_scan_failure_and_success_restore_same_choice_in_same_window(self):
        self.app.targets = [pc(), pc(2)]
        self.app.filter_targets()
        self.choose(1)
        self.app.events.put(('scan_error', 'synthetic failure'))
        self.app.pump()
        self.assertEqual(self.app.target_box.cget('values'), '')
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.app.events.put(('targets', dict(targets=[pc(2), pc()], warnings=[])))
        self.app.pump()
        self.assertEqual(self.app.selected_target(), pc(2))
        self.assertEqual(self.app.start_button.cget('state'), 'normal')
        self.assertFalse(list(Path(self.temp.name).rglob('state.json')))


if __name__ == '__main__':
    unittest.main()
