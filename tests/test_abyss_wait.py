"""A running battle may be observed without authorizing entry. No native inputs."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from abyss_core import Observation, Token, Scene, Session, Reading, PauseRequired, classify
from assistant_config import atomic_json
from assistant_worker import StopRun, abyss_run
from pc_backend import PcSafetyError


def observation(*texts, battle=False):
    return Observation(1200, 675, [Token(t, 600, 300, 80, 24) for t in texts],
                       visuals={'battle-pause'} if battle else set())


class BattleObservationTests(unittest.TestCase):
    def test_hud_is_recognized_without_entry_provenance(self):
        for verified in (False, True):
            self.assertEqual(classify(observation(battle=True), verified).scene, Scene.BATTLE)

    def test_attaching_to_battle_waits_without_authorizing_or_inventing_floor(self):
        session = Session()
        obs = observation(battle=True)
        self.assertIsNone(session.plan(classify(obs), obs))
        self.assertEqual(session.phase, 'battle')
        self.assertFalse(session.normal_verified)
        self.assertIsNone(session.expected_floor)
        self.assertIsNone(session.entered_floor)
        self.assertIsNone(session.battle_started_at)
        self.assertEqual(session.wins, 0)
        with self.assertRaises(PauseRequired):
            session.plan(Reading(Scene.TEAM, floor=58), observation('战斗开始'))

    def test_attaching_then_seeing_clear_uses_baseline_not_fabricated_win(self):
        session = Session()
        battle = observation(battle=True)
        session.plan(classify(battle), battle)
        obs = Observation(1200, 675, [Token('下一层', 1050, 610, 80, 24)])
        action = session.plan(Reading(Scene.CLEAR, floor=58), obs)
        self.assertEqual((session.wins, session.baseline_floor), (0, 58))
        self.assertEqual((action.kind, action.target_floor), ('advance', 59))

    def test_tracked_battle_preserves_floor_and_counts_only_independent_clear(self):
        session = Session(normal_verified=True, expected_floor=58, entered_floor=58,
                          phase='battle_opening', battle_started_at=1)
        obs = observation(battle=True)
        self.assertIsNone(session.plan(classify(obs), obs))
        self.assertEqual((session.expected_floor, session.wins), (58, 0))
        clear = Observation(1200, 675, [Token('下一层', 1050, 610, 80, 24)])
        session.plan(Reading(Scene.CLEAR, floor=58), clear)
        self.assertEqual((session.wins, session.last_won_floor), (1, 58))

    def test_battle_hud_does_not_override_defeat_paid_or_capacity_prompts(self):
        for text, expected in [('战斗失败', Scene.DEFEAT), ('购买体力', Scene.BLOCKED),
                               ('确认', Scene.BLOCKED), ('装备背包已满', Scene.CAPACITY)]:
            self.assertEqual(classify(observation(text, battle=True)).scene, expected)


class BattleWorkerWaitTests(unittest.TestCase):
    def run_frames(self, frames, session=None, final_error=None, expected_error=StopRun, expect_attention=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state_path = root / 'state.json'
            atomic_json(state_path, {'attempted': {'old': {'outcome': 'defeat'}},
                                     'completed': {}, 'active': {'key': 'old'}})
            key = hashlib.sha256(b'pc|fake.exe').hexdigest()[:24]
            history_path = root / 'abyss-history.json'
            atomic_json(history_path, {'schema': 1, 'clients': {key: {
                'attempted': {'58': {'requested_at': 1}}, 'completed': {}}}})
            before = {p: p.read_bytes() for p in (state_path, history_path)}
            request = dict(home=folder, settings=dict(observe=False, task='abyss'),
                           target=dict(client='pc', exe='fake.exe'))
            control = Mock()
            if expect_attention:control.attention.side_effect = StopRun()
            clock = [1300.0]
            control.sleep.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
            snap = SimpleNamespace(image=Image.new('RGB', (1200, 675)), captured_at=1300)
            transport = Mock()
            bank = Mock(entries=[True])
            bank.apply.side_effect = frames
            session = session or Session()
            final_error = final_error or StopRun()
            with patch('assistant_transport.UnifiedTransport', return_value=transport), \
                 patch('rapidocr_onnxruntime.RapidOCR', return_value=lambda _: ([], None)), \
                 patch('abyss_templates.TemplateBank', return_value=bank), \
                 patch('abyss_core.Session', return_value=session), \
                 patch('assistant_portable.enabled', return_value=False), \
                 patch('assistant_worker.validate_run', return_value=(root, {})), \
                 patch('assistant_worker.capture_fresh', side_effect=[snap] * len(frames) + [final_error]), \
                 patch('assistant_worker.time.monotonic', side_effect=lambda: clock[0]):
                with self.assertRaises(expected_error):
                    abyss_run(request, control)
            transport.tap.assert_not_called()
            transport.swipe.assert_not_called()
            if expect_attention:control.attention.assert_called_once()
            else:control.attention.assert_not_called()
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)
            return control, session, clock[0] - 1300

    def test_start_mid_battle_keeps_waiting_beyond_fifteen_seconds(self):
        control, session, elapsed = self.run_frames([observation(battle=True) for _ in range(10)])
        self.assertGreater(elapsed, 15)
        self.assertEqual(session.phase, 'battle')
        self.assertIsNone(session.expected_floor)
        self.assertTrue(all(call.kwargs['wins'] == 0 for call in control.status.call_args_list))
        self.assertEqual(control.status.call_args.args[0], '正在自动战斗，等待结算。')
        self.assertEqual(control.status.call_args.kwargs['scene'], Scene.BATTLE.value)

    def test_unknown_frames_wait_without_claiming_game_is_unresponsive(self):
        control, _, elapsed = self.run_frames([observation() for _ in range(20)])
        self.assertGreater(elapsed, 15)
        self.assertEqual(control.status.call_args.args[0], '正在识别当前画面，暂不操作。')
        self.assertTrue(all(call.kwargs['mode'] == 'run' for call in control.status.call_args_list))

    def test_long_tracked_battle_is_not_stopped_by_elapsed_time_alone(self):
        session = Session(normal_verified=True, expected_floor=58, entered_floor=58,
                          phase='battle', battle_started_at=1)
        _, session, _ = self.run_frames([observation(battle=True) for _ in range(3)], session)
        self.assertEqual((session.expected_floor, session.wins), (58, 0))

    def test_animation_gaps_do_not_discard_tracked_battle(self):
        session = Session(normal_verified=True, expected_floor=58, entered_floor=58,
                          phase='battle_opening', battle_started_at=1)
        frames = [observation(battle=True)] * 2 + [observation()] * 20 + [observation(battle=True)] * 2
        _, session, _ = self.run_frames(frames, session)
        self.assertEqual((session.phase, session.expected_floor, session.wins), ('battle', 58, 0))

    def test_actual_target_change_waits_for_explicit_user_action_not_auto_retry(self):
        self.run_frames([observation()], final_error=PcSafetyError('所选窗口已变化'),
                        expect_attention=True)

    def test_defeat_after_long_wait_still_stops_without_retry(self):
        self.run_frames([observation()] * 20 + [observation('战斗失败', battle=True)],
                        expected_error=PauseRequired)

    def test_changing_popup_keeps_observing_without_losing_history(self):
        frames=[observation('确认', '变化中的说明'+str(i)) for i in range(25)]
        control, _, _=self.run_frames(frames)
        self.assertEqual(control.status.call_args.kwargs['mode'],'waiting_scene')

    def test_stable_unknown_popup_requires_explicit_user_handling(self):
        self.run_frames([observation('确认')]*20,expect_attention=True)


if __name__ == '__main__':
    unittest.main()
