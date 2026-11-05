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
from task_timing import ScreenStabilityGate,needs_stability_wait


RESULT = [('获得的道具', 1453, 60), ('战斗结果', 1260, 825), ('确认', 1442, 825)]
TRANSITION = [('CLEAR', 807, 559), ('战斗结果', 1260, 825), ('确认', 1442, 825)]


def frame(words):
    rows = [([[x-15, y-10], [x+15, y-10], [x+15, y+10], [x-15, y+10]], text, .99)
            for text, x, y in words]
    return runner.Frame(runner.np.full((900, 1600, 3), 50, runner.np.uint8), rows)


def victory_frame(banner='CLEAR', shade=50, extra=()):
    f = frame([('3/3', 212, 26), (banner, 807, 559),
               ('关卡任务', 364, 718), ('关卡任务', 782, 718), ('关卡任务', 1202, 718),
               ('闯关成功', 364, 749), *extra])
    f.image[:] = shade
    f.image[700:730, 275:305] = (0, 180, 0)
    return f


class VictoryControlTests(unittest.TestCase):
    def test_result_objectives_outrank_shared_legacy_clear_banner(self):
        from story_core import clear_banner
        for banner in ('CLEAR', 'C L E A R', 'C L', ''):
            with self.subTest(banner=banner):
                f = victory_frame(banner)
                if banner in ('CLEAR', 'C L E A R'):self.assertTrue(clear_banner(f))
                self.assertTrue(runner.victory_objectives_verified(f))
                self.assertEqual(runner.classify(f), 'victory')

    def test_only_complete_objectives_allow_victory_to_bypass_stability(self):
        self.assertTrue(needs_stability_wait('victory'))
        self.assertFalse(needs_stability_wait('victory', victory_verified=True))
        self.assertTrue(needs_stability_wait('unknown_dialog', victory_verified=True))
        for index in range(2, 6):
            f = victory_frame('')
            f.words.pop(index)
            self.assertFalse(runner.victory_objectives_verified(f))
        f = victory_frame(''); f.image[680:755, 245:320] = 0
        self.assertFalse(runner.victory_objectives_verified(f))

    def test_resources_defeat_and_unknown_confirm_still_veto_victory(self):
        for text, scene in [('购买体力', 'resource_stop'), ('装备背包已满', 'capacity_stop'),
                            ('战斗失败', 'defeat'), ('确认', 'unknown_dialog')]:
            f = victory_frame(extra=[(text, 800, 450)])
            self.assertTrue(runner.victory_objectives_verified(f))
            self.assertEqual(runner.classify(f), scene)

    def test_legacy_clear_without_result_objectives_keeps_legacy_handler(self):
        f = frame([('3/3', 212, 26), ('CLEAR', 807, 559)])
        self.assertFalse(runner.victory_objectives_verified(f))
        self.assertEqual(runner.classify(f), 'legacy_story_clear')
        self.assertFalse(needs_stability_wait(runner.classify(f)))


class StabilityGateTests(unittest.TestCase):
    def test_known_pages_and_business_guards_outrank_full_screen_animation_wait(self):
        for scene in ('story','skip_confirm','tutorial_skip','tutorial_skip_confirm',
                      'settlement','story_reward','unlock_notice','bond_notice','rankup',
                      'rankup_splash','account_upgrade_notice','friendship_upgrade_notice',
                      'friend_decline','lobby','map','support','team','legacy_story_map',
                      'legacy_story_regions','legacy_story_clear','legacy_story_exit','post_clear_exit',
                      'battle','capacity_stop','resource_stop','defeat','network_error'):
            self.assertFalse(needs_stability_wait(scene),scene)
        for scene in ('unknown','unknown_dialog','loading','result_transition'):
            self.assertTrue(needs_stability_wait(scene),scene)

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
    def exercise(self, frames, *, pc=False, ensure_errors=(), step_error=None, stop_on_sleep=False, late_navigation=False, initial_state=None):
        instances = []; clock = [0.0]; readings = iter(frames)
        original = {'attempted': {'current': {'keep': True}}, 'completed': {},
                    'active': {'key': 'current'}, 'last_cleared': {'key': 'older'}}
        if initial_state is not None:original = copy.deepcopy(initial_state)
        class FakeRunner(runner.Runner):
            def __init__(self, **kwargs):
                self.s = copy.deepcopy(original); self.cfg = {'start_policy': 'current_screen'}
                self.pc = None; self.ticket = None; self.last_mode = None; self.mode_since = time.time()
                self.unknown_gestures = 0; self.input_sequence = 0; self.seen = []
                self.action = Mock(side_effect=lambda *a,**k:setattr(self,'input_sequence',self.input_sequence+1))
                self.save = Mock(); self.evidence = Mock(return_value='synthetic.png')
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

    def test_animated_story_background_cannot_starve_verified_skip(self):
        dark=frame([('跳过',1500,35)]);bright=frame([('跳过',1500,35)]);bright.image[:]=150
        r,ctl,_=self.exercise([dark,bright])
        self.assertEqual(r.seen,['story']);r.action.assert_called_once()
        self.assertEqual(r.action.call_args.args[0],'跳过剧情')
        self.assertFalse(any(c.kwargs.get('mode')=='waiting_scene' for c in ctl.status.call_args_list))

    def test_animated_skip_confirmation_cannot_starve_verified_confirm(self):
        words=[('跳过故事',800,400),('确认',800,500)]
        dark=frame(words);bright=frame(words);bright.image[:]=150
        r,ctl,_=self.exercise([dark,bright])
        self.assertEqual(r.seen,['skip_confirm']);r.action.assert_called_once()
        self.assertEqual(r.action.call_args.args[0],'确认跳过剧情')
        self.assertFalse(any(c.kwargs.get('mode')=='waiting_scene' for c in ctl.status.call_args_list))

    def test_animated_victory_and_clear_ocr_flicker_reach_continue_without_completion(self):
        r, ctl, original = self.exercise([victory_frame(), victory_frame('C L', 150)])
        self.assertEqual(r.seen, ['victory']); r.action.assert_called_once()
        self.assertEqual(r.action.call_args.kwargs['xy'], (1550, 845))
        self.assertTrue(r.s['active']['victory_seen'])
        self.assertEqual(r.s['completed'], {}); self.assertEqual(r.s['attempted'], original['attempted'])
        self.assertEqual(r.s['last_cleared'], original['last_cleared'])
        self.assertFalse(any(c.kwargs.get('mode')=='waiting_scene' for c in ctl.status.call_args_list))

    def test_victory_then_independent_settlement_completes_only_at_settlement(self):
        r, ctl, original = self.exercise([victory_frame(), frame(RESULT), frame(RESULT)])
        self.assertEqual(r.seen, ['victory', 'settlement']); ctl.attention.assert_not_called()
        self.assertEqual(list(r.s['completed']), ['current']); self.assertIsNone(r.s['active'])
        self.assertEqual(r.s['attempted'], original['attempted']); self.assertEqual(r.action.call_count, 2)
        self.assertEqual(r.action.call_args.args[1]['text'], '确认')

    def test_current_screen_victory_never_completes_archived_entry(self):
        original = {'attempted': {'archived': {'keep': True}}, 'completed': {}, 'active': None,
                    'last_cleared': {'key': 'older'}, 'unresolved_entries': [{'entry': {'key': 'archived'}}]}
        r, ctl, _ = self.exercise([victory_frame(), frame(RESULT), frame(RESULT)], initial_state=original)
        self.assertEqual(r.seen, ['victory', 'settlement']); self.assertEqual(r.action.call_count, 2)
        ctl.attention.assert_not_called()
        for key in original:self.assertEqual(r.s[key], original[key])

    def test_victory_priority_still_recaptures_expired_frame_and_rejects_geometry(self):
        r, ctl, _ = self.exercise([victory_frame(), victory_frame('C L', 150)], pc=True,
                                  ensure_errors=[FrameExpired(), None])
        self.assertEqual(r.seen, ['victory']); r.action.assert_called_once(); ctl.attention.assert_not_called()
        r, ctl, original = self.exercise([victory_frame()], pc=True,
                                         ensure_errors=[PcSafetyError('geometry changed')])
        self.assertEqual(r.seen, []); r.action.assert_not_called(); self.assertEqual(r.s, original)
        self.assertEqual(ctl.attention.call_args.args[0].code, 'client_input')

    def test_animated_unknown_confirm_over_victory_still_waits_with_zero_input(self):
        frames = [victory_frame(shade=shade, extra=[('确认', 800, 450)]) for shade in (50, 150)*10]
        r, ctl, original = self.exercise(frames)
        self.assertEqual(r.seen, []); self.assertEqual(r.s, original)
        r.action.assert_not_called(); ctl.attention.assert_not_called()

    def test_victory_without_complete_objectives_still_waits_for_stability(self):
        words = [('CLEAR', 807, 559), ('关卡任务', 364, 718), ('闯关成功', 364, 749)]
        dark = frame(words); bright = frame(words); bright.image[:] = 150
        self.assertEqual(runner.classify(dark), 'victory')
        r, ctl, original = self.exercise([dark, bright]*10)
        self.assertEqual(r.seen, []); self.assertEqual(r.s, original)
        r.action.assert_not_called(); ctl.attention.assert_not_called()

    def test_animated_settlement_with_changing_incidental_ocr_confirms_on_first_frame(self):
        dark = frame(RESULT+[('MVP', 200, 210), ('exp+15600', 180, 90)])
        bright = frame(RESULT+[('MVP', 205, 212), ('装饰文字', 400, 400)])
        bright.image[:] = 150
        r, ctl, original = self.exercise([dark, bright])
        self.assertEqual(r.seen, ['settlement']); r.action.assert_called_once()
        self.assertEqual(r.action.call_args.args[1]['text'], '确认')
        self.assertEqual(list(r.s['completed']), ['current'])
        self.assertEqual(r.s['attempted'], original['attempted'])
        self.assertFalse(any(c.kwargs.get('mode')=='waiting_scene' for c in ctl.status.call_args_list))

    def test_known_free_controls_do_not_wait_for_animated_characters_or_background(self):
        cases = [
            ([('故事完成奖励已正常发放',800,300),('点击关闭',800,600)], 'story_reward'),
            ([('支线故事通知',800,200),('已解锁 支线故事一览',800,320),('点击关闭',800,650)], 'unlock_notice'),
            ([('升级！',800,230),('账号升等，行动力上限已提升',800,400),('点击关闭',800,650)], 'account_upgrade_notice'),
            ([('英雄亲密度等级上升',800,230),('轻触后关闭',800,650)], 'friendship_upgrade_notice'),
            ([('变更日期',800,270),('日期变更，将前往大厅。',802,448),('点击关闭',802,599)], 'date_change_notice'),
        ]
        for words, scene in cases:
            with self.subTest(scene=scene):
                dark = frame(words); bright = frame(words); bright.image[:] = 150
                r, ctl, original = self.exercise([dark, bright])
                self.assertEqual(r.seen, [scene]); r.action.assert_called_once()
                self.assertEqual(r.s['completed'], original['completed'])
                self.assertFalse(any(c.kwargs.get('mode')=='waiting_scene' for c in ctl.status.call_args_list))

    def test_business_interrupts_are_handled_on_first_moving_frame_without_input(self):
        for text, scene, code in [('购买体力','resource_stop','resource'),('装备背包已满','capacity_stop','equipment')]:
            with self.subTest(scene=scene):
                f = frame(RESULT+[(text,800,400)])
                r, ctl, original = self.exercise([f])
                self.assertEqual(r.seen,[scene]); r.action.assert_not_called()
                self.assertEqual(ctl.attention.call_args.args[0].code, code)
                for key in original:self.assertEqual(r.s[key],original[key])

    def test_animated_settlement_keeps_freshness_and_target_guards_before_confirm(self):
        r, ctl, original = self.exercise([frame(RESULT)], pc=True,
                                         ensure_errors=[PcSafetyError('geometry changed')])
        self.assertEqual(r.seen, []); r.action.assert_not_called(); self.assertEqual(r.s, original)
        self.assertEqual(ctl.attention.call_args.args[0].code, 'client_input')
        r, ctl, _ = self.exercise([frame(RESULT), frame(RESULT)], pc=True,
                                  ensure_errors=[FrameExpired(),None])
        self.assertEqual(r.seen,['settlement']); r.action.assert_called_once(); ctl.attention.assert_not_called()


if __name__ == '__main__':unittest.main()
