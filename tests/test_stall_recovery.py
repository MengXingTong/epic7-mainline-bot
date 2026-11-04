"""Offline frame sequences only; no game input or real progress mutations."""
import copy
import json
import os
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import runner
from assistant_worker import mainline_run, PlanningFrameGate, StopRun
from pc_backend import PcBackend, PcSafetyError, FrameExpired, NavigationFrameExpired, InputDeliveryError, WindowSnapshot
from task_blockers import TaskAttention
from task_overlays import battle_settlement_confirm
from task_timing import ScreenStabilityGate


RESULT = [('获得的道具', 1453, 60), ('战斗结果', 1260, 825), ('确认', 1442, 825)]
TRANSITION = [('CLEAR', 807, 559), ('战斗结果', 1260, 825), ('确认', 1442, 825)]


def frame(words):
    rows = [([[x-15, y-10], [x+15, y-10], [x+15, y+10], [x-15, y+10]], text, .99)
            for text, x, y in words]
    return runner.Frame(runner.np.full((900, 1600, 3), 50, runner.np.uint8), rows)


class StabilityGateTests(unittest.TestCase):
    def test_transient_dialog_waits_without_reclassifying_it_as_success(self):
        clock = [0.0]; gate = ScreenStabilityGate(lambda: clock[0]); im = frame(TRANSITION).image
        self.assertEqual(runner.classify(frame(TRANSITION)), 'unknown_dialog')
        self.assertTrue(gate.waiting('unknown_dialog', im))
        clock[0] = 3.99; self.assertTrue(gate.waiting('unknown_dialog', im))
        clock[0] = 4; self.assertFalse(gate.waiting('unknown_dialog', im))
        clock[0] = 90; self.assertFalse(gate.waiting('unknown_dialog', im))

    def test_recognized_page_and_explicit_reset_start_a_new_observation_window(self):
        clock = [0.0]; gate = ScreenStabilityGate(lambda: clock[0]); im = frame(RESULT).image
        gate.waiting('unknown_dialog', im); clock[0] = 9
        self.assertTrue(gate.waiting('settlement', im))
        clock[0] = 10; self.assertFalse(gate.waiting('settlement', im))
        self.assertTrue(gate.waiting('unknown_dialog', im))
        clock[0] = 20; gate.reset(); self.assertTrue(gate.waiting('unknown_dialog', im))

    def test_stable_resource_capacity_and_defeat_still_take_priority(self):
        clock = [0.0]; gate = ScreenStabilityGate(lambda: clock[0])
        for text, scene in [('购买体力', 'resource_stop'), ('装备背包已满', 'capacity_stop'),
                            ('战斗失败', 'defeat')]:
            f = frame(TRANSITION + [(text, 800, 400)]); actual = runner.classify(f)
            self.assertEqual(actual, scene); self.assertTrue(gate.waiting(actual, f.image, f.words))
            clock[0] += 1; self.assertFalse(gate.waiting(actual, f.image, f.words))

    def test_continuously_moving_image_waits_for_hours_without_deadline(self):
        clock = [0.0]; gate = ScreenStabilityGate(lambda: clock[0])
        for index in range(200):
            clock[0] = index * 60
            im = runner.np.full((90, 160, 3), 40 if index%2 else 140, runner.np.uint8)
            self.assertTrue(gate.waiting('unknown_dialog', im))
        clock[0] += 3.9; self.assertTrue(gate.waiting('unknown_dialog', im))
        clock[0] += .2; self.assertFalse(gate.waiting('unknown_dialog', im))

    def test_control_motion_and_page_changes_restart_quiet_period(self):
        clock = [0.0]; gate = ScreenStabilityGate(lambda: clock[0]); im = frame(RESULT).image
        for index in range(20):
            clock[0] = index*10
            words = frame([('确认', 800+index*30, 500)]).words
            self.assertTrue(gate.waiting('unknown_dialog', im, words))
        clock[0] += 4; self.assertFalse(gate.waiting('unknown_dialog', im, words))
        self.assertTrue(gate.waiting('team', im, words))

    def test_small_ocr_jitter_does_not_wait_forever_but_slow_fades_accumulate(self):
        clock = [0.0]; gate = ScreenStabilityGate(lambda: clock[0]); im = frame(RESULT).image
        gate.waiting('settlement', im, frame(RESULT).words); clock[0] = 1
        self.assertFalse(gate.waiting('settlement', im, frame([(t, x+2, y-2) for t,x,y in RESULT]).words))
        gate.reset(); clock[0] = 0; gate.waiting('unknown_dialog', im)
        for index in range(1, 10):
            clock[0] = index
            self.assertTrue(gate.waiting('unknown_dialog', im+index))


class SettlementControlTests(unittest.TestCase):
    def test_positive_settlement_returns_the_exact_observed_button(self):
        f = frame(RESULT)
        self.assertEqual(runner.classify(f), 'settlement')
        self.assertIs(battle_settlement_confirm(f.words), f.words[-1])

    def test_center_duplicate_low_confidence_or_missing_controls_do_not_settle(self):
        cases = [RESULT[:2] + [('确认', 800, 500)], RESULT + [('确定', 800, 500)],
                 RESULT[1:], RESULT[::2], RESULT + [('取消', 800, 500)]]
        for words in cases:
            with self.subTest(words=words):
                f = frame(words)
                self.assertIsNone(battle_settlement_confirm(f.words))
                self.assertEqual(runner.classify(f), 'unknown_dialog')
        for index in range(3):
            f = frame(RESULT); f.words[index]['score'] = .7
            self.assertEqual(runner.classify(f), 'unknown_dialog')

    def test_unknown_confirm_vetoes_underlying_pages(self):
        backgrounds = [[('Episode 4', 150, 40), ('准备战斗', 1400, 825)],
                       [('选择辅助英雄', 800, 80), ('选择队伍', 1400, 825)],
                       [('3/3', 212, 26)], [('跳过', 1500, 35)],
                       [('故事完成奖励已正常发放', 800, 300), ('点击关闭', 800, 600)]]
        for background in backgrounds:
            self.assertEqual(runner.classify(frame(background + [('确认', 800, 450)])), 'unknown_dialog')


class PlanningFreshnessTests(unittest.TestCase):
    def test_expiry_recaptures_before_planning_then_resets_budget(self):
        backend = Mock(); backend.ensure.side_effect = [FrameExpired(), None, FrameExpired(), None]
        gate = PlanningFrameGate()
        self.assertEqual([gate.ready(backend) for _ in range(4)], [False, True, False, True])
        backend.tap.assert_not_called()

    def test_persistent_expiry_keeps_refreshing_without_authorizing_input(self):
        backend = Mock(); backend.ensure.side_effect = FrameExpired()
        gate = PlanningFrameGate()
        for _ in range(200):self.assertFalse(gate.ready(backend))
        backend.tap.assert_not_called()

    def test_geometry_delivery_and_consumed_frame_errors_never_become_refresh(self):
        for error in (PcSafetyError('geometry changed'), InputDeliveryError('uncertain')):
            backend = Mock(); backend.ensure.side_effect = error
            with self.assertRaises(type(error)):PlanningFrameGate().ready(backend)
            backend.tap.assert_not_called()
        self.assertTrue(PlanningFrameGate().ready(None))

    def test_native_guard_prioritizes_geometry_and_identity_over_expiry(self):
        window = WindowSnapshot(1, 2, 'EpicSeven.exe', 3, 0, 0, 1600, 900)
        api = Mock(); api.ready.return_value = True; api.windows.return_value = [window]
        api.capture.return_value = runner.np.full((900, 1600, 3), 50, runner.np.uint8)
        clock = [0.0]
        with tempfile.TemporaryDirectory() as folder:
            backend = PcBackend(dict(game_exe=window.exe), Path(folder)/'STOP', api=api, clock=lambda: clock[0])
            backend.allowed = True; backend.capture(); clock[0] = 6
            with self.assertRaises(FrameExpired):backend.ensure()
            for changed in (replace(window, x=10), replace(window, pid=4)):
                api.windows.return_value = [changed]
                with self.assertRaises(PcSafetyError) as caught:backend.ensure()
                self.assertNotIsInstance(caught.exception, FrameExpired)
            api.windows.return_value = [window]; backend.frame_at = None
            with self.assertRaises(PcSafetyError) as caught:backend.ensure()
            self.assertNotIsInstance(caught.exception, FrameExpired)
            api.button.assert_not_called()


class LateNavigationExpiryTests(unittest.TestCase):
    def make_runner(self, root, api, clock):
        window=WindowSnapshot(1,2,'EpicSeven.exe',3,0,0,1600,900)
        api.ready.return_value=True;api.windows.return_value=[window]
        api.capture.return_value=runner.np.full((900,1600,3),50,runner.np.uint8)
        backend=PcBackend(dict(game_exe=window.exe),root/'STOP',api=api,clock=lambda:clock[0])
        backend.allowed=True;backend.capture()
        r=runner.Runner.__new__(runner.Runner);r.pc=backend;r.ticket=None
        r.frame=frame([('选择队伍',1400,825)])
        r.s={'screen':'support','attempted':{},'completed':{},'active':None}
        r.save=Mock(side_effect=lambda:clock.__setitem__(0,clock[0]+6))
        return r

    def test_expiry_during_save_does_not_send_and_next_fresh_plan_uses_new_target(self):
        with tempfile.TemporaryDirectory() as folder,patch('runner.event'):
            api=Mock();clock=[0.0];r=self.make_runner(Path(folder),api,clock)
            with self.assertRaises(NavigationFrameExpired):r.action('选择当前队伍',r.frame.words[0])
            api.button.assert_not_called();self.assertEqual(r.s['attempted'],{})
            r.pc.capture();r.frame=frame([('选择队伍',1380,820)]);r.save.side_effect=None
            r.action('选择当前队伍',r.frame.words[0])
            self.assertEqual(api.move.call_args.args,(1380,820))
            self.assertEqual([call.args for call in api.button.call_args_list],[(True,),(False,)])

    def test_entry_or_unknown_delivery_never_becomes_navigation_refresh(self):
        for kind,active in [('进行任务（仅一次入场）',None),('选择当前队伍',{'key':'reserved'})]:
            with tempfile.TemporaryDirectory() as folder,patch('runner.event'):
                api=Mock();clock=[0.0];r=self.make_runner(Path(folder),api,clock);r.s['active']=active
                with self.assertRaises(FrameExpired) as caught:r.action(kind,r.frame.words[0])
                self.assertNotIsInstance(caught.exception,NavigationFrameExpired);api.button.assert_not_called()
        with tempfile.TemporaryDirectory() as folder,patch('runner.event'):
            api=Mock();clock=[0.0];r=self.make_runner(Path(folder),api,clock);r.save.side_effect=None
            api.button.side_effect=InputDeliveryError('uncertain delivery')
            with self.assertRaises(InputDeliveryError):r.action('选择当前队伍',r.frame.words[0])

    def test_key_record_failure_and_geometry_change_still_stop(self):
        with tempfile.TemporaryDirectory() as folder,patch('runner.event'):
            api=Mock();clock=[0.0];r=self.make_runner(Path(folder),api,clock)
            r.save.side_effect=OSError('cannot persist')
            with self.assertRaises(OSError):r.action('选择当前队伍',r.frame.words[0])
            api.button.assert_not_called()
            def changed():
                clock[0]=6;api.windows.return_value=[replace(api.windows.return_value[0],x=20)]
            r.save.side_effect=changed
            with self.assertRaises(PcSafetyError) as caught:r.action('选择当前队伍',r.frame.words[0])
            self.assertNotIsInstance(caught.exception,NavigationFrameExpired);api.button.assert_not_called()


class WorkerSequenceTests(unittest.TestCase):
    def exercise(self, frames, *, pc=False, ensure_errors=(), step_error=None, stop_on_sleep=False, late_navigation=False):
        instances = []; clock = [0.0]; readings = iter(frames)
        original = {'attempted': {'current': {'keep': True}}, 'completed': {},
                    'active': {'key': 'current'}, 'last_cleared': {'key': 'older'}}
        class FakeRunner(runner.Runner):
            def __init__(self, **kwargs):
                self.s = copy.deepcopy(original); self.cfg = {'start_policy': 'current_screen'}
                self.pc = None; self.ticket = None; self.last_mode = None; self.mode_since = time.time()
                self.unknown_gestures = 0; self.input_sequence = 0; self.seen = []
                self.action = Mock(); self.save = Mock(); self.evidence = Mock(return_value='synthetic.png')
                instances.append(self)
            def start_current_screen(self):pass
            def capture(self):
                clock[0] += 1.5  # Simulated capture/OCR time; never sleep in a test.
                try:self.frame = next(readings); return self.frame
                except StopIteration:raise StopRun()
            def step(self, f):
                self.seen.append(runner.classify(f))
                if late_navigation and len(self.seen)==1:
                    self.s['screen']='support';raise NavigationFrameExpired('ordinary tap not sent')
                if step_error:
                    self.s['attempted']['new'] = {'intent': True}
                    raise step_error
                return super().step(f)
        ctl = Mock(); ctl.attention.side_effect = StopRun()
        def sleep(seconds):
            if stop_on_sleep:raise StopRun()
            clock[0] += seconds
        ctl.sleep.side_effect = sleep
        story = SimpleNamespace(total_wins=lambda: 0, context=False, stage_label=lambda: '', step=lambda *a: None)
        backend = Mock(); backend.ensure.side_effect = list(ensure_errors) if ensure_errors else None
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=False):
            root = Path(folder)
            target = dict(client='pc', hwnd=1, pid=2, created=3, exe='EpicSeven.exe', title='test') if pc else dict(client='mumu', serial='fake', package='fake')
            request = dict(run_dir=folder, settings=dict(observe=False, task='mainline', mumu={}, pc_input='messages'), target=target)
            with patch('assistant_worker.validate_run', return_value=(root, {})), patch.object(runner, 'ROOT', root), \
                 patch('runner.Runner', FakeRunner), patch('runner.event'), \
                 patch('story_core.StoryController', return_value=story), \
                 patch('assistant_worker.ScreenStabilityGate', side_effect=lambda: ScreenStabilityGate(lambda: clock[0])), \
                 patch('pc_backend.PcBackend', return_value=backend), patch('pc_message_backend.MessageWin32Api'):
                with self.assertRaises(StopRun):mainline_run(request, ctl)
        return instances[0], ctl, original

    def test_animation_then_real_settlement_completes_once_without_attention(self):
        r, ctl, original = self.exercise([frame(TRANSITION), frame(RESULT), frame(RESULT)])
        self.assertEqual(r.seen, ['settlement']); ctl.attention.assert_not_called()
        self.assertEqual(list(r.s['completed']), ['current']); self.assertIsNone(r.s['active'])
        self.assertEqual(r.s['attempted'], original['attempted']); r.action.assert_called_once()
        self.assertEqual(r.action.call_args.args[1]['text'], '确认')

    def test_persistent_dialog_waits_then_requires_explicit_continue(self):
        r, ctl, original = self.exercise([frame(TRANSITION)]*20)
        self.assertEqual(r.seen, ['unknown_dialog']); r.action.assert_not_called()
        self.assertEqual(ctl.attention.call_args.args[0].code, 'dialog')
        for key in original:self.assertEqual(r.s[key], original[key])

    def test_stop_during_dialog_wait_does_not_reach_planning(self):
        r, ctl, original = self.exercise([frame(TRANSITION)], stop_on_sleep=True)
        self.assertEqual(r.seen, []); self.assertEqual(r.s, original); r.action.assert_not_called()

    def test_expired_frame_is_discarded_before_step(self):
        r, ctl, original = self.exercise([frame(RESULT)]*3, pc=True, ensure_errors=[FrameExpired(), None])
        self.assertEqual(r.seen, ['settlement']); r.action.assert_called_once(); ctl.attention.assert_not_called()

    def test_stale_failure_inside_step_never_replays_intent(self):
        r, ctl, _ = self.exercise([frame(RESULT)]*2, pc=True, step_error=FrameExpired('late expiry'))
        self.assertEqual(r.seen, ['settlement']); r.action.assert_not_called()
        self.assertEqual(r.s['attempted']['new'], {'intent': True})
        self.assertEqual(ctl.attention.call_args.args[0].code, 'client_input')

    def test_ordinary_unsent_navigation_refreshes_instead_of_asking_user(self):
        r,ctl,original=self.exercise([frame(RESULT)]*4,pc=True,late_navigation=True)
        self.assertEqual(r.seen,['settlement','settlement']);ctl.attention.assert_not_called()
        r.action.assert_called_once();self.assertEqual(r.s['attempted'],original['attempted'])
        recoveries=[call for call in ctl.status.call_args_list if call.kwargs.get('mode')=='recovering']
        self.assertEqual(recoveries[0].kwargs['scene'],'support')

    def test_geometry_failure_before_step_requires_user(self):
        r, ctl, original = self.exercise([frame(RESULT)]*2, pc=True, ensure_errors=[PcSafetyError('geometry changed')])
        self.assertEqual(r.seen, []); self.assertEqual(r.s, original); r.action.assert_not_called()
        self.assertEqual(ctl.attention.call_args.args[0].code, 'client_input')

    def test_saved_incident_sequence(self):
        directory = Path(os.environ.get('EPIC7_STALL_FIXTURES', str(Path(__file__).resolve().parents[1]/'.local/stall-audit-20261104')))
        frames = []
        for name in ('reported', 'current'):
            if not (directory/(name+'-ocr.json')).is_file():self.skipTest('Private incident frames are not distributed')
            data = json.loads((directory/(name+'-ocr.json')).read_text(encoding='utf-8'))
            im = runner.cv2.imdecode(runner.np.frombuffer((directory/(name+'.png')).read_bytes(), runner.np.uint8), runner.cv2.IMREAD_COLOR)
            frames.append(runner.Frame(runner.cv2.resize(im, (1600, 900)), [(w['box'], w['text'], w['score']) for w in data['words']]))
        r, ctl, _ = self.exercise(frames+[frames[-1]])
        self.assertEqual(r.seen, ['settlement']); ctl.attention.assert_not_called()
        self.assertEqual(list(r.s['completed']), ['current']); r.action.assert_called_once()

    def test_changing_dialog_keeps_worker_observing_without_attention_or_intent(self):
        bright = frame(TRANSITION); bright.image[:] = 150
        frames = [frame(TRANSITION), bright]*110
        r, ctl, original = self.exercise(frames)
        self.assertEqual(r.seen, []); self.assertEqual(r.s, original)
        r.action.assert_not_called(); ctl.attention.assert_not_called()
        self.assertTrue(all(c.kwargs['mode']=='waiting_scene' for c in ctl.status.call_args_list))


if __name__ == '__main__':unittest.main()
