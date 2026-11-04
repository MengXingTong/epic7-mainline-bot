"""Standard-size Abyss OCR with native-coordinate taps; all transport calls are fake."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from abyss_core import Scene, Session, PauseRequired, classify
from assistant_config import atomic_json
from assistant_worker import read_abyss_observation, abyss_run, StopRun


def rows(extra=()):
    words = [('准备战斗', 148, 42), ('深渊', 1194, 110),
             ('第66层', 1204, 160), ('战斗开始', 1441, 820), *extra]
    return [([[x-20, y-10], [x+20, y-10], [x+20, y+10], [x-20, y+10]], text, .99)
            for text, x, y in words]


def bank():
    result = Mock(entries=[True])
    result.apply.side_effect = lambda image, obs: obs
    return result


class AbyssOcrScaleTests(unittest.TestCase):
    def test_ocr_uses_standard_bgr_image_while_observation_keeps_native_frame(self):
        image = Image.new('RGB', (1124, 632), (17, 91, 203))
        ocr = Mock(return_value=(rows(), None)); templates = bank()
        obs = read_abyss_observation(image, ocr, templates, 123.5)
        pixels = ocr.call_args.args[0]
        self.assertEqual(pixels.shape, (900, 1600, 3))
        self.assertEqual(pixels[100, 100].tolist(), [203, 91, 17])
        self.assertEqual((obs.width, obs.height, obs.captured_at), (1124, 632, 123.5))
        self.assertIs(templates.apply.call_args.args[0], image)
        self.assertEqual(image.size, (1124, 632))

    def test_coordinate_mapping_matrix_does_not_use_standard_pixels_for_native_taps(self):
        for width, height in [(640, 360), (1124, 632), (1280, 720), (1600, 900),
                              (2560, 1440), (3840, 2160)]:
            with self.subTest(size=(width, height)):
                obs = read_abyss_observation(Image.new('RGB', (width, height)),
                                             Mock(return_value=(rows(), None)), bank(), 100)
                reading = classify(obs, True)
                self.assertEqual((reading.scene, reading.floor), (Scene.TEAM, 66))
                session = Session(normal_verified=True, expected_floor=66, entered_floor=66,
                                  phase='next_opening')
                action = session.plan(reading, obs)
                self.assertEqual((action.kind, action.target_floor), ('start_battle', 66))
                self.assertAlmostEqual(action.token.center[0], 1441 * width / 1600)
                self.assertAlmostEqual(action.token.center[1], 820 * height / 900)
                self.assertTrue(0 < action.token.center[0] < width)
                self.assertTrue(0 < action.token.center[1] < height)

    def test_empty_ocr_keeps_native_template_processing_without_creating_text(self):
        image = Image.new('RGB', (1124, 632)); templates = bank()
        obs = read_abyss_observation(image, Mock(return_value=(None, None)), templates, 100)
        self.assertEqual(obs.tokens, [])
        self.assertEqual(classify(obs).scene, Scene.UNKNOWN)
        templates.apply.assert_called_once_with(image, obs)

    def test_existing_confidence_cutoff_is_not_lowered_to_read_mode_title(self):
        weak = rows(); weak[1] = (weak[1][0], weak[1][1], .64)
        obs = read_abyss_observation(Image.new('RGB', (1124, 632)),
                                     Mock(return_value=(weak, None)), bank(), 100)
        self.assertIsNone(obs.find('深渊'))
        self.assertEqual(classify(obs).scene, Scene.UNKNOWN)

    def test_title_outside_its_mode_region_is_not_accepted(self):
        altered = rows(); altered[1] = ([[20, 200], [60, 200], [60, 220], [20, 220]], '深渊', .99)
        obs = read_abyss_observation(Image.new('RGB', (1124, 632)),
                                     Mock(return_value=(altered, None)), bank(), 100)
        self.assertEqual(classify(obs).scene, Scene.UNKNOWN)

    def test_challenge_and_resource_overlays_still_veto_preparation(self):
        for extra, expected in [([('挑战模式', 900, 450)], Scene.HARD),
                                 ([('购买体力', 800, 450)], Scene.BLOCKED),
                                 ([('确认', 800, 450)], Scene.BLOCKED)]:
            obs = read_abyss_observation(Image.new('RGB', (1124, 632)),
                                         Mock(return_value=(rows(extra), None)), bank(), 100)
            self.assertEqual(classify(obs, True).scene, expected)

    def test_normalization_does_not_override_expected_floor(self):
        obs = read_abyss_observation(Image.new('RGB', (1124, 632)),
                                     Mock(return_value=(rows(), None)), bank(), 100)
        session = Session(normal_verified=True, expected_floor=67, entered_floor=67)
        with self.assertRaisesRegex(PauseRequired, '层数与预期不一致'):
            session.plan(classify(obs, True), obs)

    def test_private_reported_1124_frame_recovers_gold_title_and_floor66(self):
        folder = Path(os.environ.get('EPIC7_ABYSS_SCALE_FIXTURES',
                          str(Path(__file__).resolve().parents[1] / '.local/abyss-prep66')))
        if not (folder / 'reported.png').is_file():
            self.skipTest('Private reported screenshot is not distributed')
        from rapidocr_onnxruntime import RapidOCR
        from abyss_core import Token, Observation
        old = json.loads((folder / 'native-ocr.json').read_text(encoding='utf-8'))
        native = Observation(old['width'], old['height'], [Token(**t) for t in old['tokens']],
                             visuals=set(old['visuals']))
        self.assertEqual(classify(native, True).scene, Scene.UNKNOWN)
        image = Image.open(folder / 'reported.png').convert('RGB')
        obs = read_abyss_observation(image, RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2), bank(), 100)
        reading = classify(obs, True)
        self.assertEqual((reading.scene, reading.floor), (Scene.TEAM, 66))
        session = Session(normal_verified=True, expected_floor=66, entered_floor=66, phase='next_opening')
        action = session.plan(reading, obs)
        self.assertEqual(action.kind, 'start_battle')
        self.assertTrue(990 < action.token.center[0] < 1040)
        self.assertTrue(550 < action.token.center[1] < 610)
        self.assertEqual(session.wins, 0)


class AbyssNormalizedWorkerTests(unittest.TestCase):
    def exercise(self, previously_attempted=False, current_start=False, completed=False, missing_floor=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); history_path = root / 'abyss-history.json'
            key = hashlib.sha256(b'pc|fake.exe').hexdigest()[:24]
            attempted = {'66': {'requested_at': 1}} if previously_attempted else {}
            cleared = {'66': {'observed_clear_at': 1}} if completed else {}
            atomic_json(history_path, {'schema': 1, 'clients': {key: {'attempted': attempted, 'completed': cleared}}})
            before = history_path.read_bytes()
            request = dict(home=folder, settings=dict(observe=False, task='abyss', pc_input='messages'),
                           target=dict(client='pc', exe='fake.exe'))
            if current_start:request['settings']['start_policy']='current_screen'
            session = Session() if current_start else Session(normal_verified=True, expected_floor=66, entered_floor=66, phase='next_opening')
            transport = Mock(); control = Mock(); clock = [100.0]
            control.attention.side_effect = StopRun()
            ocr_rows = [row for row in rows() if not (missing_floor and row[1] == '第66层')]
            control.sleep.side_effect = lambda seconds: clock.__setitem__(0, clock[0] + seconds)
            snap = SimpleNamespace(image=Image.new('RGB', (1124, 632)), captured_at=100)
            def entered(frame, token, ordinary_gate=False):
                ledger = json.loads(history_path.read_text())['clients'][key]
                self.assertIn('66', ledger['attempted'])
                self.assertNotIn('66', ledger['completed'])
                self.assertIs(frame, snap)
                self.assertAlmostEqual(token.center[0], 1441 * 1124 / 1600)
                self.assertAlmostEqual(token.center[1], 820 * 632 / 900)
            transport.tap.side_effect = entered
            with patch('assistant_transport.UnifiedTransport', return_value=transport), \
                 patch('rapidocr_onnxruntime.RapidOCR', return_value=Mock(return_value=(ocr_rows, None))), \
                 patch('abyss_templates.TemplateBank', return_value=bank()), \
                 patch('abyss_core.Session', return_value=session), \
                 patch('assistant_portable.enabled', return_value=False), \
                 patch('assistant_worker.validate_run', return_value=(root, {})), \
                 patch('assistant_worker.capture_fresh', side_effect=[snap] * 3 + [StopRun()]), \
                 patch('assistant_worker.time.monotonic', side_effect=lambda: clock[0]):
                with self.assertRaises(ValueError if previously_attempted and not current_start else StopRun):
                    abyss_run(request, control)
            transport.swipe.assert_not_called()
            if previously_attempted or completed or missing_floor:
                transport.tap.assert_not_called()
                self.assertEqual(history_path.read_bytes(), before)
                if current_start:
                    control.attention.assert_called_once()
                    self.assertIsNone(session.expected_floor)
            else:
                transport.tap.assert_called_once()
                self.assertEqual(session.phase, 'battle_opening')
                self.assertEqual(session.wins, 0)

    def test_worker_records_entry_before_one_native_coordinate_tap(self):
        self.exercise()

    def test_previous_entry_still_prevents_reopening_normalized_preparation(self):
        self.exercise(previously_attempted=True)

    def test_explicit_current_start_can_attach_to_verified_unattempted_preparation(self):
        self.exercise(current_start=True)

    def test_current_start_does_not_bypass_prior_attempt(self):
        self.exercise(current_start=True, previously_attempted=True)

    def test_current_start_does_not_reopen_a_completed_only_floor(self):
        self.exercise(current_start=True, completed=True)

    def test_current_start_never_infers_a_missing_floor(self):
        self.exercise(current_start=True, missing_floor=True)


if __name__ == '__main__':
    unittest.main()
