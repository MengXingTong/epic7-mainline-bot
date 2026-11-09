"""Selection regression tests: synthetic targets only; never open/control a game."""
import copy
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from assistant_selection import TargetSelection


def pc(number=1, **extra):
    return dict(dict(client='pc', hwnd=number, pid=100 + number, created=1000 + number,
                     exe='EpicSeven.exe', label=f'PC {number}', title='第七史诗'), **extra)


def mumu(number=0, **extra):
    return dict(dict(client='mumu', serial=f'127.0.0.1:{16384 + number * 32}',
                     package='example.game', mumu_index=number, label=f'MuMu {number}'), **extra)


class TargetSelectionTests(unittest.TestCase):
    def setUp(self):
        self.selection = TargetSelection()

    def assert_blocked(self, phrase):
        self.assertFalse(self.selection.ready)
        with self.assertRaisesRegex(ValueError, phrase):
            self.selection.target()

    def select_first_of_two(self):
        self.selection.refresh([pc(), pc(2)], 'auto')
        self.selection.choose('PC 1')

    def test_unscanned_requires_discovery(self):
        self.assert_blocked('尚未检测')

    def test_zero_targets_is_not_reported_as_multiple(self):
        self.selection.refresh([], 'pc')
        self.assert_blocked('未检测到电脑客户端')
        self.assertNotIn('多个', self.selection.message)

    def test_unique_target_is_selected(self):
        target = pc()
        self.selection.refresh([target], 'auto')
        self.assertIs(self.selection.target(), target)

    def test_multiple_targets_need_explicit_selection(self):
        self.selection.refresh([pc(), mumu()], 'auto')
        self.assert_blocked('绑定实例')
        self.selection.choose('MuMu 0')
        self.assertEqual(self.selection.target(), mumu())

    def test_refresh_preserves_choice_even_if_order_changes(self):
        self.select_first_of_two()
        self.selection.refresh([pc(2), pc()], 'auto')
        self.assertEqual(self.selection.target(), pc())

    def test_refresh_uses_new_target_details_not_old_label_or_geometry(self):
        self.select_first_of_two()
        updated = pc(label='resized PC', width=1920, height=1080, title='Epic Seven')
        self.selection.refresh([updated, pc(2)], 'auto')
        self.assertIs(self.selection.target(), updated)
        self.assertEqual(self.selection.display, 'resized PC')

    def test_recycled_hwnd_same_label_does_not_bind_new_process(self):
        for change in (dict(pid=999), dict(created=9999), dict(exe='other/EpicSeven.exe')):
            with self.subTest(change=change):
                self.selection = TargetSelection()
                self.selection.refresh([pc()], 'auto')
                self.selection.refresh([pc(**change)], 'auto')
                self.assert_blocked('身份发生变化')

    def test_missing_choice_never_falls_back_to_only_other_target(self):
        self.select_first_of_two()
        self.selection.refresh([pc(2)], 'auto')
        self.assert_blocked('原绑定实例')
        self.selection.refresh([pc(2)], 'auto')
        self.assert_blocked('原绑定实例')

    def test_zero_targets_then_different_singleton_does_not_auto_switch(self):
        self.selection.refresh([pc()], 'auto')
        self.selection.refresh([], 'auto')
        self.assert_blocked('未检测到')
        self.selection.refresh([pc(2)], 'auto')
        self.assert_blocked('原绑定实例')

    def test_exact_original_target_can_return_after_temporarily_missing(self):
        self.select_first_of_two()
        self.selection.refresh([], 'auto')
        self.selection.refresh([pc(2), pc()], 'auto')
        self.assertEqual(self.selection.target(), pc())

    def test_explicit_reselection_recovers_in_same_model(self):
        self.select_first_of_two()
        self.selection.refresh([pc(2)], 'auto')
        self.selection.choose('PC 2')
        self.assertEqual(self.selection.target(), pc(2))

    def test_filter_change_preserves_still_matching_manual_choice(self):
        self.select_first_of_two()
        self.selection.refresh([pc(), pc(2), mumu()], 'pc')
        self.assertEqual(self.selection.target(), pc())

    def test_explicit_client_filter_may_narrow_to_a_different_unique_target(self):
        self.selection.refresh([pc(), mumu()], 'auto')
        self.selection.choose('PC 1')
        self.selection.refresh([pc(), mumu()], 'mumu')
        self.assertEqual(self.selection.target(), mumu())

    def test_explicit_filter_with_multiple_targets_still_needs_choice(self):
        self.selection.refresh([pc()], 'auto')
        self.selection.refresh([pc(), mumu(), mumu(1)], 'mumu')
        self.assert_blocked('检测到2个目标')

    def test_failed_discovery_invalidates_cached_candidates(self):
        self.select_first_of_two()
        self.selection.fail('synthetic timeout')
        self.assertEqual(self.selection.rows, [])
        self.assertEqual(self.selection.labels, [])
        self.assert_blocked('检测失败')
        with self.assertRaises(ValueError):
            self.selection.choose('PC 1')

    def test_successful_refresh_after_failure_recovers_original_binding(self):
        self.select_first_of_two()
        self.selection.fail('timeout')
        self.selection.refresh([pc(2), pc()], 'auto')
        self.assertEqual(self.selection.target(), pc())

    def test_only_other_target_after_failure_is_not_selected(self):
        self.select_first_of_two()
        self.selection.fail('timeout')
        self.selection.refresh([pc(2)], 'auto')
        self.assert_blocked('原绑定实例')

    def test_duplicate_names_are_unique_choices_and_keep_structured_binding(self):
        a, b = pc(label='same'), pc(2, label='same')
        self.selection.refresh([a, b], 'auto')
        self.assertEqual(len(set(self.selection.labels)), 2)
        self.selection.choose(self.selection.labels[1])
        self.assertIs(self.selection.target(), b)
        self.selection.refresh([b, a], 'auto')
        self.assertIs(self.selection.target(), b)
        self.assertEqual(self.selection.display, self.selection.labels[0])

    def test_generated_display_suffix_cannot_collide_with_an_actual_name(self):
        self.selection.refresh([pc(label='same'), pc(2, label='same'), pc(3, label='same · 候选 #1')], 'auto')
        self.assertEqual(len(set(self.selection.labels)), 3)
        for label, target in zip(self.selection.labels, self.selection.rows):
            self.selection.choose(label)
            self.assertIs(self.selection.target(), target)

    def test_duplicate_identity_is_not_two_selectable_instances(self):
        self.selection.refresh([pc(), pc(label='duplicate')], 'auto')
        self.assert_blocked('重复的实例身份')
        self.assertEqual(self.selection.labels, [])

    def test_incomplete_or_invalid_identity_cannot_start(self):
        targets = [pc(hwnd=True), pc(pid=0), pc(created=None), pc(created=float('nan')),
                   pc(created=float('inf')), pc(exe=''), mumu(serial=''), mumu(package=None),
                   mumu(mumu_index=True), dict(client='other', label='unknown')]
        for target in targets:
            with self.subTest(target=target):
                self.selection.refresh([target], 'auto')
                self.assertFalse(self.selection.ready)
                self.assertEqual(self.selection.phase, 'invalid')

    def test_malformed_discovery_cannot_leave_old_ready_candidates(self):
        for targets in (None, {}, [None], [123], ['not a target']):
            with self.subTest(targets=targets):
                self.selection = TargetSelection()
                self.selection.refresh([pc()], 'auto')
                self.selection.refresh(targets, 'auto')
                self.assert_blocked('检测结果无效')
                self.assertEqual(self.selection.rows, [])

    def test_missing_or_invalid_label_is_not_selectable(self):
        for label in (None, '', 123):
            self.selection.refresh([pc(label=label)], 'auto')
            self.assertFalse(self.selection.ready)
            self.assertEqual(self.selection.phase, 'invalid')

    def test_unknown_choice_cannot_change_binding(self):
        self.select_first_of_two()
        with self.assertRaises(ValueError):
            self.selection.choose('not a candidate')
        self.assertEqual(self.selection.target(), pc())

    def test_changed_cached_identity_is_rejected_before_start(self):
        target = pc()
        self.selection.refresh([target], 'auto')
        target['created'] += 1
        self.assert_blocked('身份发生变化')

    def test_mumu_aliases_agree_but_endpoint_package_and_known_index_must_match(self):
        self.selection.refresh([mumu()], 'auto')
        self.selection.refresh([mumu(serial='localhost:16384', label='renamed')], 'auto')
        self.assertTrue(self.selection.ready)
        for change in (dict(serial='127.0.0.1:16416'), dict(package='different.game'), dict(mumu_index=1)):
            with self.subTest(change=change):
                self.selection = TargetSelection()
                self.selection.refresh([mumu()], 'auto')
                self.selection.refresh([mumu(**change)], 'auto')
                self.assert_blocked('原绑定实例')

    def test_selection_does_not_mutate_discovery_or_progress(self):
        targets = [pc(), mumu()]
        original = copy.deepcopy(targets)
        self.selection.refresh(targets, 'auto')
        self.selection.choose('MuMu 0')
        self.selection.fail('timeout')
        self.selection.refresh(targets, 'auto')
        self.assertEqual(targets, original)

    def test_selection_module_is_in_portable_and_update_source_allowlist(self):
        import build_portable
        self.assertIn('assistant_selection.py', build_portable.SOURCES)


try:
    from assistant_app import Assistant
except ImportError:
    Assistant = None


class Var:
    def __init__(self, value=''):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Widget:
    def __init__(self):
        self.values = {}
    def configure(self, **values):
        self.values.update(values)
    def cget(self, key):
        return self.values.get(key)


@unittest.skipIf(Assistant is None, 'GUI imports required; no actual Tk window is created')
class SelectionWiringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        a = self.app = Assistant.__new__(Assistant)
        a.selection = TargetSelection()
        a.targets = []
        a.filtered = []
        a.client = Var('自动识别')
        a.instance = Var()
        a.task = Var('推进剧情关卡')
        a.status = Var()
        for name in ('target_box', 'refresh_button', 'start_button', 'pause_button', 'stop_button'):
            setattr(a, name, Widget())
        a.process = None
        a.scanning = False
        a.mode = 'idle'
        a.read_only = False
        a.home = Path(self.temp.name) / 'assistant'
        a.base_home = Path(self.temp.name)
        a.slot_number = 1
        a.settings = dict(task='mainline', worker_python=sys.executable, mumu={})
        a.current_settings = Mock(side_effect=lambda: dict(a.settings))
        a.run_id = 'old-run'
        a.run_dir = None
        a.started = None
        a.events = queue.Queue()
        a.closing = True
        a.pending_restart = None
        a.gui_command_id = None
        a.update_note = Mock()
        a.update_activity = Mock()
        a.log = Mock()
        a.launch_worker = Mock()
        a.command = Mock()

    def choose_first_of_two(self):
        self.app.targets = [pc(), pc(2)]
        self.app.filter_targets()
        self.app.instance.set('PC 1')
        self.app.choose_target()

    def test_no_target_disables_start_but_direct_call_is_also_guarded(self):
        self.app.filter_targets()
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        with patch('assistant_app.atomic_json') as write, patch('assistant_instances.resolve_target_profile') as resolve:
            self.app.start()
        write.assert_not_called()
        resolve.assert_not_called()
        self.app.launch_worker.assert_not_called()
        self.assertIn('未检测到', self.app.status.get())
        self.assertEqual(self.app.run_id, 'old-run')

    def test_choice_event_enables_start_and_refresh_preserves_it(self):
        self.app.targets = [pc(), pc(2)]
        self.app.filter_targets()
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.app.instance.set('PC 1')
        self.app.choose_target()
        self.app.targets.reverse()
        self.app.filter_targets()
        self.assertEqual(self.app.start_button.cget('state'), 'normal')
        self.assertEqual(self.app.selected_target(), pc())

    def test_target_identity_not_stringvar_drives_binding(self):
        self.choose_first_of_two()
        self.app.instance.set('PC 2')  # No selection event: cannot silently rebind.
        with self.assertRaisesRegex(ValueError, '尚未核实'):
            self.app.selected_target()
        self.app.update_buttons()
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')

    def test_reselect_after_error_reaches_mock_launch_without_reextracting(self):
        self.app.targets = [pc(), pc(2)]
        self.app.filter_targets()
        self.app.start()
        self.assertEqual(self.app.mode, 'blocked')
        self.app.instance.set('PC 2')
        self.app.choose_target()
        self.assertEqual(self.app.mode, 'idle')
        with patch('assistant_app.validate_run'), patch('assistant_portable.save_settings'), patch('assistant_app.atomic_json'):
            self.app.start()
        self.app.launch_worker.assert_called_once()
        self.assertEqual(self.app.launch_worker.call_args.args[0]['target'], pc(2))
        self.assertFalse(list(Path(self.temp.name).rglob('state.json')))

    def test_new_singleton_after_original_disappears_requires_reselection(self):
        self.choose_first_of_two()
        self.app.targets = [pc(2)]
        self.app.filter_targets()
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.assertIn('原绑定实例', self.app.status.get())
        self.app.instance.set('PC 2')
        self.app.choose_target()
        self.assertEqual(self.app.start_button.cget('state'), 'normal')

    def test_successful_scan_event_does_not_replace_actionable_prompt(self):
        self.app.events.put(('targets', dict(targets=[pc(), pc(2)], warnings=['synthetic warning'])))
        self.app.pump()
        self.assertIn('绑定实例', self.app.status.get())
        self.assertIn('synthetic warning', self.app.status.get())
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')

    def test_scan_error_clears_old_ui_candidates_and_can_recover(self):
        self.choose_first_of_two()
        self.app.scanning = True
        self.app.events.put(('scan_error', 'synthetic timeout'))
        self.app.pump()
        self.assertEqual(self.app.targets, [])
        self.assertEqual(self.app.filtered, [])
        self.assertEqual(self.app.target_box.cget('values'), [])
        self.assertIn('检测失败', self.app.status.get())
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.app.events.put(('targets', dict(targets=[pc(2), pc()], warnings=[])))
        self.app.pump()
        self.assertEqual(self.app.selected_target(), pc())
        self.assertEqual(self.app.start_button.cget('state'), 'normal')

    def test_scanning_disables_and_guards_start_even_with_old_selection(self):
        self.choose_first_of_two()
        self.app.scanning = True
        self.app.update_buttons()
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.app.start()
        self.app.launch_worker.assert_not_called()
        self.assertIn('正在检测', self.app.status.get())

    def test_discovery_settings_write_failure_does_not_latch_scanning(self):
        self.choose_first_of_two()
        with patch('assistant_app.atomic_json', side_effect=PermissionError('synthetic locked discovery file')), patch('assistant_app.threading.Thread') as thread:
            self.app.scan()
        thread.assert_not_called()
        self.app.pump()
        self.assertFalse(self.app.scanning)
        self.assertEqual(self.app.refresh_button.cget('state'), 'normal')
        self.assertEqual(self.app.start_button.cget('state'), 'disabled')
        self.assertIn('检测失败', self.app.status.get())
        self.app.events.put(('targets', dict(targets=[pc(), pc(2)])))
        self.app.pump()
        self.assertEqual(self.app.selected_target(), pc())

    def test_discovery_thread_start_failure_does_not_latch_scanning(self):
        self.choose_first_of_two()
        with patch('assistant_app.threading.Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('synthetic thread failure')
            self.app.scan()
        self.app.pump()
        self.assertFalse(self.app.scanning)
        self.assertIn('检测失败', self.app.status.get())
        self.assertEqual(self.app.refresh_button.cget('state'), 'normal')

    def test_malformed_worker_response_uses_recoverable_scan_error(self):
        from types import SimpleNamespace
        def immediate_thread(*, target, daemon):
            return SimpleNamespace(start=target)
        for payload in ('[]', '{}', '{"targets": null}', '{"targets": [], "mumu": null}',
                        '{"targets": [], "warnings": null}', '{"targets": [], "warnings": [1]}'):
            with self.subTest(payload=payload):
                self.choose_first_of_two()
                result = SimpleNamespace(returncode=0, stdout=payload)
                with patch('assistant_app.threading.Thread', side_effect=immediate_thread), patch('assistant_app.subprocess.run', return_value=result):
                    self.app.scan()
                self.app.pump()
                self.assertFalse(self.app.scanning)
                self.assertEqual(self.app.filtered, [])
                self.assertEqual(self.app.start_button.cget('state'), 'disabled')
                self.assertIn('检测失败', self.app.status.get())

    def test_live_paused_or_attention_worker_continues_without_reselection(self):
        for mode in ('paused', 'attention'):
            with self.subTest(mode=mode):
                self.app.process = Mock()
                self.app.process.poll.return_value = None
                self.app.mode = mode
                self.app.update_buttons()
                self.assertEqual(self.app.start_button.cget('state'), 'normal')
                self.app.start()
                self.app.command.assert_called_with('run')
                self.app.launch_worker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
