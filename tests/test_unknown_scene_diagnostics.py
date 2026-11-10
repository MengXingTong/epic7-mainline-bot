"""Unknown animated region maps explain missing identity, never grant input."""
import copy
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import runner
from assistant_worker import mainline_run
from story_core import walking_map_info
from test_story_only_nodes import fake_runner, frame as mainline_frame


OVERVIEW = [('示例地区', 134, 42), ('任务', 1542, 232), ('地区信息', 1538, 369),
            ('1.银杉森林', 321, 523), ('2.清泉溪谷', 802, 445),
            ('3.高地草原', 1240, 636), ('成就', 795, 826),
            ('交易所', 1024, 826), ('准备战斗', 1266, 827)]


def overview(rows=None, shade=50):
    rows = OVERVIEW if rows is None else rows
    results = [([[x-15, y-10], [x+15, y-10], [x+15, y+10], [x-15, y+10]], text, .999)
               for text, x, y in rows]
    return runner.Frame(runner.np.full((900, 1600, 3), shade, runner.np.uint8), results)


class UnknownSceneDiagnosticTests(unittest.TestCase):
    def test_complete_region_shell_uses_shared_walking_map_without_episode_guess(self):
        f = overview()
        self.assertEqual(runner.classify(f), 'legacy_story_map')
        self.assertEqual(walking_map_info(f)['region'], '示例地区')
        self.assertIsNone(runner.mainline_map_control(f))
        self.assertTrue(all(row['id'] is None for row in walking_map_info(f)['rows']))

    def test_region_name_is_not_a_hardcoded_title_allowlist(self):
        rows = [('另一地区' if text == '示例地区' else text, x, y) for text, x, y in OVERVIEW]
        self.assertEqual(runner.classify(overview(rows)), 'legacy_story_map')

    def test_partial_duplicate_low_confidence_and_displaced_shell_are_generic_unknown(self):
        for index in (0, 1, 2, 6, 7, 8):
            with self.subTest(missing=index):
                f = overview(OVERVIEW[:index] + OVERVIEW[index+1:])
                self.assertIsNone(walking_map_info(f))
            with self.subTest(weak=index):
                f = overview(); f.words[index]['score'] = .89
                self.assertIsNone(walking_map_info(f))
            with self.subTest(displaced=index):
                f = overview(); f.words[index]['x'] = 600; f.words[index]['y'] = 100
                self.assertIsNone(walking_map_info(f))
            with self.subTest(duplicate=index):
                f = overview(); f.words.append(copy.deepcopy(f.words[index]))
                self.assertIsNone(walking_map_info(f))

    def test_short_number_alone_is_not_a_complete_stage_identity(self):
        f=overview([row for row in OVERVIEW if row[0] not in ('2.清泉溪谷','3.高地草原')])
        self.assertEqual(runner.classify(f),'legacy_story_map')
        self.assertIsNone(walking_map_info(f)['rows'][0]['id'])
        duplicate=overview([(text.replace('2.','1.').replace('3.','1.'),x,y) for text,x,y in OVERVIEW])
        self.assertIsNone(walking_map_info(duplicate))

    def test_known_mainline_and_business_vetoes_are_not_reclassified(self):
        self.assertEqual(runner.classify(mainline_frame()), 'map')
        self.assertEqual(runner.unknown_scene_diagnostic(mainline_frame())['code'], 'unknown_scene')
        for text, expected in [('购买体力', 'resource_stop'), ('装备背包已满', 'capacity_stop'),
                               ('战斗失败', 'defeat'), ('确认', 'unknown_dialog'),
                               ('点击关闭', 'unknown_dialog')]:
            self.assertEqual(runner.classify(overview(OVERVIEW + [(text, 800, 450)])), expected)

    def test_stable_unknown_runner_preserves_all_entry_history_without_any_input(self):
        r = fake_runner(overview(OVERVIEW[:7] + OVERVIEW[8:])); r.run_id = 'same-run'
        history = dict(attempted={'old': {'outcome': 'defeat'}}, completed={'done': {'proof': 'kept'}},
                       active={'key': 'pending', 'cost': 8}, last_cleared={'key': 'done'},
                       entry_dispatches={'pending': [{'id': 'original', 'status': 'sent'}]},
                       archived_active=[{'key': 'older'}])
        r.s.update(copy.deepcopy(history))
        r.adb = Mock(); r.pc = Mock()
        r.pc.tap.side_effect = AssertionError('unknown page must never receive input')
        r.action.side_effect = AssertionError('unknown page must never receive input')
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)), patch.object(runner, 'event'):
            keep, _ = r.step(r.frame)
        self.assertTrue(keep)
        self.assertEqual({key: r.s[key] for key in history}, history)
        self.assertEqual(r.s['screen'], 'unknown')
        self.assertIn('尚无已核实控件', r.s['reason'])
        self.assertEqual(r.observation_wait['code'], 'unknown_scene')
        r.action.assert_not_called(); r.back.assert_not_called(); r.adb.assert_not_called(); r.pc.tap.assert_not_called()

    def test_animated_unknown_worker_reports_identity_gap_then_accepts_known_page(self):
        frames = [overview(OVERVIEW[:7] + OVERVIEW[8:],shade=shade) for shade in (50, 100, 150)] + [mainline_frame()]
        instances = []
        class FakeRunner:
            def __init__(self, **kwargs):
                self.pc = None; self.ticket = None; self.mode_since = 0; self.input_sequence = 0
                self.s = dict(completed={}, attempted={'old': {'outcome': 'defeat'}}, active=None)
                self.frames = iter(frames); self.steps = []
                instances.append(self)
            def start_current_screen(self):
                pass
            def capture(self):
                return next(self.frames)
            def step(self, f):
                self.steps.append(runner.classify(f))
                return False, 0
        control = Mock()
        story = SimpleNamespace(total_wins=lambda: 0, context=False, stage_label=lambda: '')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=False):
            root = Path(folder)
            request = dict(run_dir=folder, settings=dict(observe=False, task='mainline', mumu={}),
                           target=dict(client='mumu', serial='fake', package='fake'))
            with patch('assistant_worker.validate_run', return_value=(root, {})), \
                 patch.object(runner, 'ROOT', root), patch.object(runner, 'Runner', FakeRunner), \
                 patch('story_core.StoryController', return_value=story), \
                 patch('assistant_worker.wait_for_input', return_value=False):
                mainline_run(request, control)
        waiting = [call for call in control.status.call_args_list if call.kwargs.get('scene') == 'unknown']
        self.assertEqual(len(waiting), 3)
        self.assertTrue(all(call.kwargs['mode'] == 'waiting_evidence' for call in waiting))
        self.assertTrue(all('尚无已核实控件' in call.args[0] for call in waiting))
        self.assertTrue(all('正在等待画面和控件稳定' not in call.args[0] for call in waiting))
        self.assertEqual(instances[0].steps, ['map'])
        self.assertEqual(instances[0].input_sequence, 0)
        self.assertEqual(instances[0].s['attempted'], {'old': {'outcome': 'defeat'}})
        control.attention.assert_not_called()


if __name__ == '__main__':
    unittest.main()
