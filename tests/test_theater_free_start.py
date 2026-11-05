"""Explicit zero-cost current-screen starts; no live windows or real inputs."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
from abyss_core import Observation, Token
from theater_core import Episode, Reading, classify, plan
from theater_directory import free_start_reading
from theater_journal import TheaterJournal
from task_blockers import TaskAttention
import test_theater as h


class FreeStartTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new('RGB', (1600, 900), '#222222')
        ImageDraw.Draw(self.image).rectangle((790, 795, 1160, 880), fill='#167b30')
        self.obs = h.observation([
            h.token('月光剧场', 150, 40), h.token('目录', 1290, 140),
            h.token('没落', 140, 180, h=100), h.token('大地', 300, 250, h=130),
            h.token('第1集·探究者', 280, 620), h.token('第1集', 1300, 260),
            h.token('可观览', 1300, 300), h.token('第2集', 1300, 390),
            h.token('无法观览', 1300, 430), h.token('进行观览', 1000, 835)],
            visuals=['theater_selected:1', 'theater_season:2'])
        self.state = {'active':None, 'actions':[], 'attempted':{}, 'completed':{}, 'entry_dispatches':{}}
        self.ep = Episode('没落大地', 1, 2)

    def read(self, obs=None, image=None, state=None):
        obs = self.obs if obs is None else obs
        return free_start_reading(self.image if image is None else image, obs, classify(obs),
                                  self.state if state is None else state)

    def test_positive_full_identity_row_and_full_green_surface_enable_only_free_open(self):
        r = self.read()
        self.assertEqual(r.scene, 'theater_free_ready')
        self.assertEqual(r.episode, self.ep)
        self.assertEqual(r.ticket_cost, 0)
        self.assertEqual(plan(r, self.state, 'new'), 'open_free')

    def test_missing_fee_ocr_does_not_make_separate_dark_fee_panel_free(self):
        image = self.image.copy()
        ImageDraw.Draw(image).rectangle((880, 795, 950, 880), fill='#18120a')
        self.assertNotEqual(self.read(image=image).scene, 'theater_free_ready')
        self.obs.tokens.append(h.token('1/12', 890, 835))
        self.assertNotEqual(self.read().scene, 'theater_free_ready')

    def test_missing_season_soft_selection_or_caption_mismatch_does_not_start(self):
        for visuals in ({'theater_selected:1'}, {'theater_soft_selected:1', 'theater_season:2'},
                        {'theater_selected:2', 'theater_season:2'}):
            obs = copy.deepcopy(self.obs); obs.visuals = visuals
            self.assertNotEqual(self.read(obs=obs).scene, 'theater_free_ready')

    def test_locked_countdown_completed_uncertain_and_missing_available_block(self):
        for text in ('无法观览', '3小时后可观览', '完成', '可获得奖励', ''):
            obs = copy.deepcopy(self.obs)
            obs.tokens[6] = h.token(text, 1300, 300)
            self.assertNotEqual(self.read(obs=obs).scene, 'theater_free_ready')
        obs = copy.deepcopy(self.obs)
        obs.tokens[6] = h.token('完成', 1300, 300)
        obs.visuals.add('theater_complete:1')
        self.assertNotEqual(self.read(obs=obs).scene, 'theater_free_ready')

    def test_resource_capacity_defeat_and_unknown_modal_have_priority(self):
        for text in ('购买门票', '英雄持有数量已达上限', '战斗失败', '点击关闭', '确认'):
            obs = copy.deepcopy(self.obs); obs.tokens.append(h.token(text, 800, 450))
            self.assertNotEqual(self.read(obs=obs).scene, 'theater_free_ready')

    def test_pending_paid_chain_cannot_be_discarded_by_free_start(self):
        state = copy.deepcopy(self.state)
        state['active'] = dict(key=Episode('没落大地', 14, 1).key, number=14, season=1,
                               series='没落大地', run_id='old', phase='await_guide')
        before = copy.deepcopy(state)
        self.assertNotEqual(self.read(state=state).scene, 'theater_free_ready')
        self.assertEqual(state, before)
        with self.assertRaises(TaskAttention):
            plan(self.read(), state, 'new')

    def test_free_surface_never_bypasses_exact_or_legacy_attempt_and_completion(self):
        r = self.read()
        for bucket in ('attempted', 'completed'):
            for key in self.ep.history_keys:
                state = copy.deepcopy(self.state); state[bucket][key] = {'key':key}
                with self.assertRaises(TaskAttention): plan(r, state, 'new')

    def test_new_start_archives_old_paid_entry_and_records_free_intent_before_send(self):
        with tempfile.TemporaryDirectory() as d:
            old = TheaterJournal(d, 'old')
            paid = Reading('theater_list', self.obs.tokens[-1], Episode('没落大地', 14, 1), ticket_cost=1, ticket_stock=6)
            record = old.reserve('open', paid, 'old-open.png'); old.finish(record, 'sent')
            record = old.reserve('ticket', paid, 'old-ticket.png'); old.finish(record, 'sent')
            before = copy.deepcopy(old.state)
            journal = TheaterJournal(d, 'new')
            self.assertEqual(journal.state['unresolved_entries'][-1]['entry'], before['active'])
            r = self.read(state=journal.state)
            record = journal.reserve(plan(r, journal.state, 'new'), r, 'free.png')
            persisted = json.loads(journal.path.read_text(encoding='utf-8'))
            self.assertEqual(persisted['actions'][-1]['status'], 'reserved')
            self.assertIn(self.ep.key, persisted['attempted'])
            journal.finish(record, 'sent')
            self.assertEqual(journal.state['active']['phase'], 'await_guide')
            self.assertEqual(journal.state['actions'][:len(before['actions'])], before['actions'])
            for key in before['attempted']:
                self.assertEqual(journal.state['attempted'][key], before['attempted'][key])
            self.assertEqual(journal.state['completed'], {})
            with self.assertRaises(TaskAttention): journal.reserve('open_free', r, 'duplicate.png')

    def test_unknown_send_stays_attempted_after_new_run_and_cannot_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            journal = TheaterJournal(d, 'one'); r = self.read(state=journal.state)
            journal.reserve('open_free', r, 'intent.png')
            again = TheaterJournal(d, 'two')
            self.assertEqual(again.state['unresolved_entries'][-1]['entry']['phase'], 'opening')
            with self.assertRaises(TaskAttention): plan(self.read(state=again.state), again.state, 'two')

    def test_worker_enters_free_once_then_guide_and_story_without_ticket(self):
        original = free_start_reading
        def with_frame_image(image, obs, reading, state):
            return original(self.image, obs, reading, state)
        with patch('theater_directory.free_start_reading', side_effect=with_frame_image):
            transport, ctl, state = h.TheaterWorkerTests().run_frames([
                self.obs, h.guide(), h.observation(visuals=['theater_story'])], processing_seconds=.001)
        self.assertEqual(transport.tap.call_count, 3)
        ctl.attention.assert_not_called()
        self.assertEqual([x['kind'] for x in state['actions']], ['open_free', 'guide', 'advance'])
        self.assertEqual(state['active']['key'], self.ep.key)
        self.assertEqual(state['active']['phase'], 'story')
        self.assertEqual(state['completed'], {})

    def test_worker_other_season_free_page_does_not_replace_existing_paid_active(self):
        transport, ctl, state = h.TheaterWorkerTests().run_frames([
            h.listing(14), h.ticket(), self.obs], processing_seconds=.001)
        self.assertEqual(transport.tap.call_count, 2)
        ctl.attention.assert_called_once()
        self.assertEqual(state['active']['number'], 14)

    def test_duplicate_fee_ocr_and_completed_reading_cannot_authorize_free(self):
        from dataclasses import replace
        r = self.read()
        self.obs.tokens.extend([h.token('1/12', 890, 825), h.token('1/12', 890, 850)])
        self.assertNotEqual(self.read().scene, 'theater_free_ready')
        with self.assertRaises(TaskAttention):
            plan(replace(r, completed=(1,)), self.state, 'new')

    def test_private_current_directory_readonly_replay(self):
        root = Path(__file__).resolve().parents[1]/'.local/theater-monitor'
        path = root/'20261105T005228.json'
        if not path.exists(): self.skipTest('不分发实际剧场私有目录截图')
        meta = json.loads(path.read_text(encoding='utf-8'))
        with Image.open(path.with_suffix('.png')) as image:
            obs = Observation(image.width, image.height, [Token(**t) for t in meta['tokens']],
                              visuals=set(meta['visuals']))
            r = free_start_reading(image, obs, classify(obs), self.state)
        self.assertEqual(r.scene, 'theater_free_ready')
        self.assertEqual(r.episode, self.ep)


class FreeReturnWaitTests(unittest.TestCase):
    def setUp(self):
        from theater_worker import free_return_pending
        fixture = FreeStartTests(); fixture.setUp()
        self.pending = free_return_pending
        self.image, self.obs, self.ep = fixture.image, fixture.obs, fixture.ep
        self.reading = classify(self.obs)
        self.state = {'active':dict(key=self.ep.key, series=self.ep.series, season=2, number=1,
                      run_id='run', phase='await_guide'),
                      'actions':[dict(kind='open_free', key=self.ep.key, episode=self.ep.key,
                                      run_id='run', status='sent')]}

    def wait(self, reading=None, state=None):
        return self.pending(self.image, self.obs, self.reading if reading is None else reading,
                            self.state if state is None else state, 'run')

    def test_exact_free_entry_return_is_zero_input_observation_only(self):
        before = copy.deepcopy(self.state)
        self.assertTrue(self.wait())
        self.assertEqual(self.state, before)
        with self.assertRaises(TaskAttention): plan(self.reading, self.state, 'run')

    def test_unsent_unknown_duplicate_wrong_run_or_entry_do_not_wait(self):
        for mode in ('missing', 'reserved', 'unknown', 'not_sent', 'duplicate', 'old', 'wrong_episode'):
            state = copy.deepcopy(self.state)
            if mode == 'missing': state['actions'] = []
            elif mode == 'duplicate': state['actions'] *= 2
            elif mode == 'old': state['actions'][0]['run_id'] = 'old'
            elif mode == 'wrong_episode': state['actions'][0]['episode'] = 'other'
            else: state['actions'][0]['status'] = mode
            self.assertFalse(self.wait(state=state))

    def test_other_episode_season_series_and_complete_controls_keep_priority(self):
        from dataclasses import replace
        for ep in (Episode(self.ep.series, 2, 2), Episode(self.ep.series, 1, 1), Episode('其他剧目', 1, 2)):
            self.assertFalse(self.wait(replace(self.reading, episode=ep)))
        for scene in ('theater_guide', 'theater_story', 'theater_unknown', 'theater_transition',
                      'theater_defeat', 'theater_unknown_dialog', 'theater_paid_ready'):
            self.assertFalse(self.wait(replace(self.reading, scene=scene)))

    def test_resource_or_dark_fee_panel_is_not_hidden_by_free_wait(self):
        from dataclasses import replace
        self.assertFalse(self.wait(replace(self.reading, reason='资源、购买或网络提示需要手动处理。')))
        image = self.image.copy(); ImageDraw.Draw(image).rectangle((880, 795, 950, 880), fill='#111111')
        self.assertFalse(self.pending(image, self.obs, self.reading, self.state, 'run'))
        self.obs.tokens.append(h.token('1/12', 890, 835))
        self.assertFalse(self.wait(classify(self.obs)))

    def test_partial_directory_waits_but_prior_guide_ticket_play_and_playback_do_not(self):
        self.assertTrue(self.wait(Reading('theater_list')))
        for kind in ('guide', 'ticket', 'play'):
            state = copy.deepcopy(self.state)
            state['actions'].append(dict(kind=kind, key=self.ep.key, run_id='run', status='reserved'))
            self.assertFalse(self.wait(state=state))
        self.state['active']['playback_evidence'] = 'playing.png'
        self.assertFalse(self.wait())

    def patch_frame_image(self):
        from theater_directory import free_play_reading
        def with_image(image, obs, reading, **kwargs):
            return free_play_reading(self.image, obs, reading, **kwargs)
        return patch('theater_directory.free_play_reading', side_effect=with_image)

    def test_worker_free_return_waits_then_first_complete_guide_acts_without_reopening(self):
        with self.patch_frame_image():
            transport, ctl, state = h.TheaterWorkerTests().run_frames([
                self.obs, self.obs, self.obs, h.guide(), h.observation(visuals=['theater_story'])],
                processing_seconds=.001)
        self.assertEqual(transport.tap.call_count, 3)
        ctl.attention.assert_not_called()
        self.assertEqual([x['kind'] for x in state['actions']], ['open_free', 'guide', 'advance'])
        self.assertEqual(state['completed'], {})
        self.assertEqual(len([c for c in ctl.status.call_args_list if c.kwargs.get('mode') == 'waiting_scene']), 2)

    def test_worker_timeout_preserves_sent_free_entry_and_never_pays_or_replays(self):
        from assistant_worker import capture_fresh as original_capture
        import time
        def fresh(*args, **kwargs):
            snap = original_capture(*args, **kwargs); snap.captured_at = time.monotonic(); return snap
        with self.patch_frame_image(), patch('assistant_worker.capture_fresh', side_effect=fresh):
            transport, ctl, state = h.TheaterWorkerTests().run_frames([self.obs]*50, processing_seconds=.4)
        self.assertEqual(transport.tap.call_count, 1)
        self.assertEqual(ctl.attention.call_args.args[0].code, 'theater_free_no_transition')
        self.assertEqual(len(state['actions']), 1)
        self.assertEqual(state['actions'][0]['kind'], 'open_free')
        self.assertEqual(state['actions'][0]['status'], 'sent')
        self.assertEqual(state['active']['phase'], 'await_guide')
        self.assertEqual(state['completed'], {})

    def test_blue_pressed_feedback_allows_observation_but_never_a_new_free_entry(self):
        from theater_directory import free_play_reading
        image = self.image.copy()
        ImageDraw.Draw(image).rectangle((960, 801, 1136, 864), fill='#2069d0')
        self.assertNotEqual(free_play_reading(image, self.obs, self.reading).scene, 'theater_free_ready')
        pending = free_play_reading(image, self.obs, self.reading, pressed_observation=True)
        self.assertEqual(pending.scene, 'theater_free_pending')
        self.assertIsNone(plan(pending, self.state, 'run'))
        self.assertTrue(self.pending(image, self.obs, self.reading, self.state, 'run'))

    def test_worker_free_return_with_purchase_overlay_stops_immediately(self):
        blocked = h.observation([h.token('购买门票', 800, 450)])
        with self.patch_frame_image():
            transport, ctl, state = h.TheaterWorkerTests().run_frames([self.obs, blocked], processing_seconds=.001)
        self.assertEqual(transport.tap.call_count, 1)
        ctl.attention.assert_called_once()
        self.assertEqual(ctl.attention.call_args.args[0].code, 'theater_blocked')

class SameRunFreeResumeTests(unittest.TestCase):
    """Persisted free-entry recovery only; never starts a live worker."""
    def opened(self, directory):
        fixture = FreeStartTests(); fixture.setUp()
        journal = TheaterJournal(directory, 'original-run')
        reading = fixture.read(state=journal.state)
        record = journal.reserve('open_free', reading, 'original-entry.png')
        journal.finish(record, 'sent')
        return journal

    def test_same_run_reload_preserves_history_then_only_confirms_existing_guide(self):
        with tempfile.TemporaryDirectory() as d:
            journal = self.opened(d)
            before = copy.deepcopy(journal.state)
            original_bytes = journal.path.read_bytes()
            reloaded = TheaterJournal(d, 'original-run')
            self.assertEqual(reloaded.path.read_bytes(), original_bytes)
            self.assertEqual(reloaded.state, before)
            reading = classify(h.guide())
            self.assertEqual(plan(reading, reloaded.state, 'original-run'), 'guide')
            record = reloaded.reserve('guide', reading, 'fresh-guide.png')
            reloaded.finish(record, 'sent')
            for field in ('attempted', 'entry_dispatches', 'completed',
                          'last_cleared', 'unresolved_entries'):
                self.assertEqual(reloaded.state[field], before[field])
            self.assertEqual(reloaded.state['actions'][:-1], before['actions'])
            self.assertEqual([a['kind'] for a in reloaded.state['actions']], ['open_free', 'guide'])
            self.assertEqual(reloaded.state['active']['phase'], 'story')
            self.assertEqual(reloaded.state['active']['run_id'], 'original-run')

    def test_reload_never_replays_reserved_sent_or_unknown_guide(self):
        for status in ('reserved', 'sent', 'unknown'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as d:
                journal = self.opened(d)
                reading = classify(h.guide())
                record = journal.reserve('guide', reading, 'first-guide.png')
                if status == 'sent':
                    journal.finish(record, 'sent')
                elif status == 'unknown':
                    record['status'] = 'unknown'
                    journal.save()
                original_bytes = journal.path.read_bytes()
                reloaded = TheaterJournal(d, 'original-run')
                with self.assertRaises(TaskAttention):
                    kind = plan(reading, reloaded.state, 'original-run')
                    reloaded.reserve(kind, reading, 'must-not-send.png')
                self.assertEqual(reloaded.path.read_bytes(), original_bytes)

    def test_attention_requires_a_new_same_run_command_not_a_living_process(self):
        from assistant_worker import Control
        with tempfile.TemporaryDirectory() as d:
            control = Control(dict(run_dir=d, run_id='original-run',
                                   settings={'task':'theater'}, target={'client':'pc'}))
            old = dict(run_id='original-run', action='run', command_id='old')
            new = dict(old, command_id='explicit-continue')
            with patch('assistant_worker.read_json', side_effect=[old, old, new]), \
                    patch('assistant_worker.time.sleep') as sleep:
                control.attention(TaskAttention('theater_blocked', 'Waiting', 'No input'))
            sleep.assert_called_once_with(.2)
            self.assertEqual(control.last['mode'], 'run')
            self.assertEqual(control.last['run_id'], 'original-run')
            self.assertEqual(control.last['attention_code'], '')
