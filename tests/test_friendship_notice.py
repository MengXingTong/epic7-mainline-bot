"""Friendship modal: saved user image and fake inputs only, never live game clicks."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runner
from abyss_core import Observation, Token, Scene, Session, classify as abyss_classify
from task_blockers import TaskAttention
from task_overlays import friendship_upgrade_notice_close
from ui_text import scene_name

NOTICE = [dict(text=t, x=x, y=y, score=.99) for t, x, y in [
    ('英雄亲密度等级上升', 946, 203), ('英雄的亲密度等级上升，缘分加深了。', 946, 292),
    ('初次见面的关系', 738, 406), ('打过招呼的关系', 1178, 406), ('轻触后关闭', 948, 698)]]
BACKGROUND = [dict(text=t, x=x, y=y, score=.99) for t, x, y in [
    ('深渊', 800, 510), ('第58层', 800, 600), ('返回', 160, 840), ('下一层', 1480, 827)]]
SETTLEMENT_BACKGROUND = [dict(text=t, x=x, y=y, score=.99) for t, x, y in [
    ('获得的道具', 1454, 61), ('战斗结果', 1259, 824), ('确认', 1442, 824)]]


def frame(words):
    rows = [([[w['x']-20, w['y']-10], [w['x']+20, w['y']-10],
              [w['x']+20, w['y']+10], [w['x']-20, w['y']+10]], w['text'], w.get('score', .99))
            for w in words]
    return runner.Frame(runner.np.zeros((900, 1600, 3), runner.np.uint8), rows)


def observation(words, width=1600, height=900):
    return Observation(width, height, [Token(w['text'], w['x']-20, w['y']-10, 40, 20,
                                          score=w.get('score', .99)) for w in words],
                       visuals={'battle-pause'})


class FriendshipNoticeTests(unittest.TestCase):
    def test_reported_labels_are_a_free_friendship_overlay(self):
        self.assertEqual(friendship_upgrade_notice_close(NOTICE)['text'], '轻触后关闭')
        self.assertEqual(runner.classify(frame(NOTICE)), 'friendship_upgrade_notice')
        self.assertEqual(abyss_classify(observation(NOTICE)).scene, Scene.FRIENDSHIP_UPGRADE)
        self.assertEqual(scene_name('friendship_upgrade_notice'), '英雄亲密度提升提示')

    def test_background_clear_and_battle_hud_do_not_hide_foreground_notice(self):
        obs = observation(NOTICE + BACKGROUND)
        self.assertEqual(abyss_classify(obs, True).scene, Scene.FRIENDSHIP_UPGRADE)
        self.assertEqual(runner.classify(frame(NOTICE + BACKGROUND)), 'friendship_upgrade_notice')

    def test_settlement_confirm_behind_notice_does_not_hide_observed_close(self):
        words = NOTICE + SETTLEMENT_BACKGROUND
        target = friendship_upgrade_notice_close(words)
        self.assertEqual(target['text'], '轻触后关闭')
        self.assertEqual(runner.classify(frame(words)), 'friendship_upgrade_notice')
        obs = observation(words)
        self.assertEqual(abyss_classify(obs, True).scene, Scene.FRIENDSHIP_UPGRADE)
        session = Session(normal_verified=True, expected_floor=58, entered_floor=58,
                          phase='battle', battle_started_at=1)
        before = copy.deepcopy(session)
        action = session.plan(abyss_classify(obs, True), obs)
        self.assertEqual(action.token.text, '轻触后关闭')
        self.assertEqual(session, before)

    def test_confirm_is_allowed_only_with_complete_settlement_background(self):
        for missing in range(2):
            words = NOTICE + [word for index, word in enumerate(SETTLEMENT_BACKGROUND)
                              if index != missing]
            self.assertIsNone(friendship_upgrade_notice_close(words))
            self.assertEqual(runner.classify(frame(words)), 'unknown_dialog')
        for change in ({'score': .79}, {'x': 900}, {'y': 500}):
            words = copy.deepcopy(NOTICE + SETTLEMENT_BACKGROUND)
            words[-1].update(change)
            self.assertIsNone(friendship_upgrade_notice_close(words))
            self.assertEqual(runner.classify(frame(words)), 'unknown_dialog')
        words = NOTICE + SETTLEMENT_BACKGROUND + [dict(text='确认', x=1440, y=820, score=.99)]
        self.assertIsNone(friendship_upgrade_notice_close(words))
        self.assertEqual(runner.classify(frame(words)), 'unknown_dialog')

    def test_abyss_closes_current_label_without_mutating_floor_or_wins(self):
        obs = observation(NOTICE + BACKGROUND)
        session = Session(normal_verified=True, expected_floor=58, entered_floor=58,
                          phase='battle', battle_started_at=1)
        before = copy.deepcopy(session)
        action = session.plan(abyss_classify(obs, True), obs)
        self.assertEqual(action.token.center, (948, 698))
        self.assertEqual(action.kind, 'click')
        self.assertNotEqual(action.token.text, '下一层')
        self.assertEqual(session, before)

    def test_independent_clear_is_counted_only_after_notice_is_gone(self):
        session = Session(normal_verified=True, expected_floor=58, entered_floor=58, phase='battle')
        obs = observation(NOTICE + BACKGROUND)
        session.applied(session.plan(abyss_classify(obs, True), obs))
        self.assertEqual((session.wins, session.expected_floor), (0, 58))
        clear = observation(BACKGROUND)
        self.assertEqual(abyss_classify(clear, True).scene, Scene.CLEAR)
        action = session.plan(abyss_classify(clear, True), clear)
        self.assertEqual((session.wins, action.kind, action.target_floor), (1, 'advance', 59))

    def make_runner(self):
        r = runner.Runner.__new__(runner.Runner)
        r.last_mode = None; r.mode_since = time.time(); r.unknown_gestures = 0
        r.ticket = {'key': 'current'}
        r.s = {'active': {'key': 'current'}, 'attempted': {'current': {'outcome': 'pending'}},
               'completed': {}, 'last_cleared': 'older'}
        r.action = Mock(); r.completed = Mock(); r.save = Mock(); r.story = Mock()
        return r

    def test_mainline_closes_before_story_and_keeps_original_history(self):
        r = self.make_runner(); before = copy.deepcopy(r.s)
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)), patch('runner.event'):
            keep, _ = r.step(frame(NOTICE + BACKGROUND))
        self.assertTrue(keep)
        r.action.assert_called_once()
        self.assertEqual((r.action.call_args.args[1]['x'], r.action.call_args.args[1]['y']), (948, 698))
        r.completed.assert_not_called(); r.story.step.assert_not_called()
        for key in ('active', 'attempted', 'completed', 'last_cleared'):
            self.assertEqual(r.s[key], before[key])

    def test_missing_or_untrusted_close_never_uses_hidden_next_floor(self):
        for changes in ({'score': .5}, {'x': 1580}, {'y': 30}):
            words = copy.deepcopy(NOTICE); words[-1].update(changes)
            self.assertIsNone(friendship_upgrade_notice_close(words))
            self.assertEqual(runner.classify(frame(words + BACKGROUND)), 'unknown_dialog')
            obs = observation(words + BACKGROUND)
            self.assertEqual(abyss_classify(obs).scene, Scene.BLOCKED)
            with self.assertRaises(TaskAttention):
                Session().plan(abyss_classify(obs), obs)
        self.assertIsNone(friendship_upgrade_notice_close(NOTICE[:-1]))
        self.assertEqual(abyss_classify(observation(NOTICE[:-1] + BACKGROUND)).scene, Scene.BLOCKED)

    def test_close_without_heading_does_not_authorize_dismissal_or_advance(self):
        words = [NOTICE[-1]] + BACKGROUND
        self.assertIsNone(friendship_upgrade_notice_close(words))
        self.assertEqual(runner.classify(frame(words)), 'unknown_dialog')
        self.assertEqual(abyss_classify(observation(words)).scene, Scene.BLOCKED)

    def test_duplicate_close_is_not_resolved_with_a_guessed_point(self):
        words = NOTICE + [dict(text='轻触后关闭', x=1000, y=720, score=.99)]
        self.assertIsNone(friendship_upgrade_notice_close(words))
        self.assertEqual(abyss_classify(observation(words)).scene, Scene.BLOCKED)

    def test_paid_resource_and_confirmation_cover_still_win(self):
        for text, mainline, abyss in [('购买体力', 'resource_stop', Scene.BLOCKED),
                                      ('确认', 'unknown_dialog', Scene.BLOCKED)]:
            words = NOTICE + [dict(text=text, x=800, y=450, score=.99)]
            self.assertIsNone(friendship_upgrade_notice_close(words))
            self.assertEqual(runner.classify(frame(words)), mainline)
            self.assertEqual(abyss_classify(observation(words)).scene, abyss)

    def test_capacity_and_defeat_still_win_over_friendship_background(self):
        for text, mainline, abyss in [('装备背包已满', 'capacity_stop', Scene.CAPACITY),
                                      ('战斗失败', 'defeat', Scene.DEFEAT)]:
            words = NOTICE + [dict(text=text, x=800, y=450, score=.99)]
            self.assertEqual(runner.classify(frame(words)), mainline)
            self.assertEqual(abyss_classify(observation(words)).scene, abyss)

    def test_traditional_labels_and_scaled_window_keep_observed_control(self):
        words = [dict(text=t, x=x, y=y, score=.99) for t, x, y in [
            ('英雄親密度等級上升', 665, 143), ('輕觸後關閉', 666, 490)]]
        target = friendship_upgrade_notice_close(words, 1124, 632)
        self.assertIs(target, words[-1])
        self.assertEqual(abyss_classify(observation(words, 1124, 632)).scene, Scene.FRIENDSHIP_UPGRADE)

    def test_new_stop_still_prevents_close(self):
        r = self.make_runner(); r.stop = Mock(return_value=(False, 0))
        with tempfile.TemporaryDirectory() as folder, patch.object(runner, 'ROOT', Path(folder)), patch('runner.event'):
            (Path(folder) / 'STOP').write_text('synthetic user stop')
            self.assertFalse(r.step(frame(NOTICE))[0])
        r.action.assert_not_called(); r.stop.assert_called_once()

    def test_private_reported_image_classifies_and_plans_only_close(self):
        directory = Path(os.environ.get('EPIC7_FRIENDSHIP_FIXTURES',
                                        str(Path(__file__).resolve().parents[1] / '.local/friendship-upgrade')))
        if not (directory / 'reported.png').is_file():
            self.skipTest('Private user image is not distributed')
        data = json.loads((directory / 'reported-ocr.json').read_text(encoding='utf-8'))
        image = runner.cv2.imdecode(runner.np.frombuffer((directory / 'reported.png').read_bytes(),
                                                       runner.np.uint8), runner.cv2.IMREAD_COLOR)
        rows = [(w['box'], w['text'], w['score']) for w in data['words']]
        f = runner.Frame(image, rows)
        self.assertEqual(runner.classify(f), 'friendship_upgrade_notice')
        obs = observation(f.words)
        session = Session(normal_verified=True, expected_floor=58, entered_floor=58, phase='battle')
        action = session.plan(abyss_classify(obs, True), obs)
        self.assertEqual(action.token.text, '轻触后关闭')
        close = next(w for w in f.words if w['text'] == '轻触后关闭')
        self.assertEqual(action.token.center, (close['x'], close['y']))
        self.assertEqual((session.expected_floor, session.wins), (58, 0))

    def test_private_settlement_background_image_plans_only_foreground_close(self):
        directory = Path(os.environ.get('EPIC7_FRIENDSHIP_FIXTURES',
                                        str(Path(__file__).resolve().parents[1] / '.local/friendship-upgrade')))
        image_path = directory / 'settlement-background.png'
        if not image_path.is_file():
            self.skipTest('Private current friendship screenshot is not distributed')
        image = runner.cv2.imdecode(runner.np.frombuffer(image_path.read_bytes(), runner.np.uint8),
                                    runner.cv2.IMREAD_COLOR)
        image = runner.cv2.resize(image, (1600, 900))
        results, _ = runner.RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)(image)
        f = runner.Frame(image, results)
        self.assertEqual(runner.classify(f), 'friendship_upgrade_notice')
        target = friendship_upgrade_notice_close(f.words)
        self.assertEqual(target['text'], '轻触后关闭')
        self.assertEqual((round(target['x']), round(target['y'])), (947, 698))


if __name__ == '__main__':
    unittest.main()
