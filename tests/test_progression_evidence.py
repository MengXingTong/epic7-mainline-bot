"""Progression contract tests: passive observations cannot cancel real progress."""
import copy
import datetime
import hashlib
import itertools
import json
from pathlib import Path
import random
import time
import unittest
from unittest.mock import patch

import runner
from assistant_status import activity
from mainline_story_results import recorded_clipped_story_completion
from progression_evidence import story_result_trace
from task_blockers import TaskAttention
from test_era_map import era_map
import test_recorded_clipped_story_results as recorded_fixtures
from test_story_only_nodes import fake_runner


KEY = 'E5-C8-S6'

def flow(skip=True):
    events = [dict(kind='action', action='观看故事（仅一次）', stage=KEY),
              dict(kind='screen', screen='story', stage=KEY)]
    if skip:
        events += [dict(kind='action', action='跳过剧情', stage=KEY),
                   dict(kind='screen', screen='skip_confirm', stage=KEY),
                   dict(kind='action', action='确认跳过剧情', stage=KEY)]
    return events + [dict(kind='screen', screen='story_reward', stage=KEY),
                     dict(kind='action', action='关闭已发放的免费奖励遮罩', stage=KEY),
                     dict(kind='screen', screen='map', stage=KEY)]


class CausalProgressionTests(unittest.TestCase):
    def test_natural_playback_and_skip_have_the_same_outcome_contract(self):
        for skip in (False, True):
            result = story_result_trace(flow(skip), KEY)
            self.assertTrue(result.proven)
            self.assertEqual(result.phase, 'returned')
            self.assertEqual([m['kind'] for m in result.proof['milestones']],
                             ['opening_message', 'playback', 'reward', 'reward_dismissal', 'returned_map'])

    def test_all_passive_transition_insertions_preserve_confirmed_milestones(self):
        # Metamorphic rather than one regression per newly encountered page.
        rng = random.Random(20261107)
        scenes = ['loading', 'result_transition', 'unknown', 'unknown_dialog', 'future_passive_animation']
        for _ in range(150):
            original = flow(rng.choice((False, True)))
            events = copy.deepcopy(original)
            for _ in range(rng.randint(1, 14)):
                events.insert(rng.randint(0, len(events)), dict(kind='screen', screen=rng.choice(scenes), stage=KEY))
            result = story_result_trace(events, KEY)
            self.assertTrue(result.proven, result)
            self.assertEqual([m['kind'] for m in result.proof['milestones']],
                             [m['kind'] for m in story_result_trace(original, KEY).proof['milestones']])

    def test_read_only_diagnostics_are_not_unaccounted_inputs(self):
        events = flow()
        for kind in ('capture_display_fallback', 'skip_control_cancelled', 'skip_control_verified',
                     'control_pixels_changed', 'control_pixels_expired'):
            events.insert(3, dict(kind=kind, stage=KEY))
        self.assertTrue(story_result_trace(events, KEY).proven)

    def test_positive_contradictions_and_actual_navigation_still_block_results(self):
        for kind, value in itertools.chain(
                (('screen', scene) for scene in ('battle', 'defeat', 'capacity_stop', 'resource_stop', 'lobby', 'team')),
                ((kind, None) for kind in ('back', 'drag', 'stop', 'completed', 'unregistered_input'))):
            events = flow()
            events.insert(3, dict(kind=kind, screen=value, stage=KEY))
            self.assertEqual(story_result_trace(events, KEY).status, 'blocked')

    def test_an_unknown_action_cannot_self_declare_a_harmless_effect(self):
        events = flow()
        events.insert(3, dict(kind='action', action='未知确认', effect='story_skip', stage=KEY))
        result = story_result_trace(events, KEY)
        self.assertEqual(result.code, 'unaccounted_input')

    def test_effect_mismatch_and_foreign_stage_are_rejected(self):
        for change in ('effect', 'stage'):
            events = flow()
            events[2][change] = 'wrong'
            self.assertEqual(story_result_trace(events, KEY).status, 'blocked')

    def test_missing_milestones_are_pending_not_completed_or_failed(self):
        for length in range(1, len(flow())):
            result = story_result_trace(flow()[:length], KEY)
            self.assertEqual(result.status, 'pending')
            self.assertFalse(result.proven)

    def test_reward_close_alone_or_a_second_open_is_not_progress(self):
        for event in (dict(kind='action', action='观看故事（仅一次）', stage=KEY),
                      dict(kind='action', action='关闭已发放的免费奖励遮罩', stage=KEY)):
            events = flow()
            events.insert(1, event)
            self.assertEqual(story_result_trace(events, KEY).status, 'blocked')

    def test_phase_does_not_rewind_after_reward(self):
        events = flow()
        events.insert(-1, dict(kind='screen', screen='story', stage=KEY))
        self.assertEqual(story_result_trace(events, KEY).code, 'playback_rewound')

    def test_bad_not_sent_claim_does_not_grant_trace_continuity(self):
        events = flow()
        events.insert(3, dict(kind='navigation_input_not_sent', proof='InputBusy'))
        self.assertEqual(story_result_trace(events, KEY).code, 'unproved_not_sent')

    def test_evidence_wait_is_live_cancellable_and_not_an_attention_latch(self):
        live = activity('waiting_evidence', alive=True, observe=False)
        self.assertTrue(live.moving)
        self.assertIn('自动推进', live.title)
        self.assertFalse(activity('waiting_evidence', alive=False).moving)
        self.assertIn('已停止', activity('waiting_evidence', alive=False).title)


class ProgressionResultIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.case = recorded_fixtures.RecordedClippedStoryTests(methodName='runTest')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.c = self.case

    def read(self, diagnostic=None):
        c = self.c
        return recorded_clipped_story_completion(c.f, c.s, c.d, c.rows, c.events,
            run_id='synthetic-run', current_binding=c.binding, root=c.root, diagnostics=diagnostic)

    def trace_file(self):
        (self.c.root/'events.jsonl').write_text('\n'.join(json.dumps(e, ensure_ascii=False) for e in self.c.events), encoding='utf8')

    def make_runner(self):
        c = self.c
        r = fake_runner(c.f)
        r.s = c.s
        r.run_id = 'synthetic-run'
        r.map_ticket = lambda f: (c.d, c.rows, '未通关蓝色当前节点')
        self.trace_file()
        return r

    def test_loading_unknown_observations_and_natural_playback_are_result_only(self):
        c = self.c
        before = copy.deepcopy(c.s)
        c.events = [e for e in c.events if e.get('action') not in ('跳过剧情', '确认跳过剧情') and e.get('screen') != 'skip_confirm']
        for scene in ('loading', 'unknown', 'unknown_dialog', 'result_transition'):
            c.events.insert(-1, dict(kind='screen', screen=scene, stage=c.o['key'], time=c.events[-2]['time']))
        self.assertIsNotNone(self.read())
        self.assertEqual(c.s, before)

    def test_previous_stage_event_in_same_clock_second_is_not_part_of_this_open(self):
        c = self.c
        c.events.insert(0, dict(kind='completed', stage='E6-C1-S0', time=c.events[0]['time']))
        self.assertIsNotNone(self.read())

    def test_missing_current_marker_is_a_named_pending_evidence_requirement(self):
        self.c.f = era_map(False)
        self.c.f.words.pop(4)
        diagnostics = {}
        self.assertIsNone(self.read(diagnostics))
        self.assertEqual(diagnostics['status'], 'pending')
        self.assertEqual(diagnostics['code'], 'map_marker')

    def test_source_integrity_error_has_a_different_diagnostic(self):
        self.c.ack['binding'] = {'client': 'other'}
        diagnostics = {}
        self.assertIsNone(self.read(diagnostics))
        self.assertEqual(diagnostics['status'], 'blocked')
        self.assertEqual(diagnostics['code'], 'acceptance_mismatch')

    def test_pending_result_keeps_observing_then_advances_without_manual_resume(self):
        c = self.c
        c.f = era_map(False)
        c.f.words.pop(4)
        r = self.make_runner();c.d['locked']=True
        original = copy.deepcopy(r.s['attempted'])
        sends = copy.deepcopy(r.s['entry_dispatches'])
        with patch.object(runner, 'ROOT', c.root), patch('runner.event'), patch('story_open_ack.binding', return_value=c.binding):
            for _ in range(3):
                keep, _ = r.step(c.f)
                self.assertTrue(keep)
                self.assertIsNotNone(r.observation_wait)
                self.assertNotIn(c.o['key'], r.s['completed'])
                r.action.assert_not_called()
            c.f = era_map();c.d['locked']=False
            c.f.words.pop(4)
            r.frame = c.f
            keep, _ = r.step(c.f)
        self.assertTrue(keep)
        self.assertIsNone(r.observation_wait)
        self.assertIn(c.o['key'], r.s['completed'])
        self.assertEqual(r.s['completed'][c.o['key']]['result_observation']['observations'], 3)
        self.assertEqual(r.s['attempted'], original)
        self.assertEqual(r.s['entry_dispatches'], sends)
        self.assertEqual(r.action.call_count, 1)
        self.assertEqual(r.action.call_args.args[0], '未通关验证通过，准备战斗')

    def test_key_persistence_failure_is_not_downgraded_to_observation_wait(self):
        c = self.c
        c.f = era_map(False)
        c.f.words.pop(4)
        r = self.make_runner()
        r.save.side_effect = OSError('critical state persistence failed')
        with patch.object(runner, 'ROOT', c.root), patch('runner.event'), patch('story_open_ack.binding', return_value=c.binding):
            with self.assertRaises(OSError):
                r.step(c.f)
        r.action.assert_not_called()

    def test_actual_current_clear_does_not_require_a_perfect_old_acceptance_log(self):
        r=self.make_runner();self.c.ack['binding']={'client':'other'}
        with patch.object(runner,'ROOT',self.c.root),patch('runner.event'):
            self.assertTrue(r.step(self.c.f)[0])
        self.assertIn(self.c.o['key'],r.s['completed'])
        self.assertEqual(r.s['completed'][self.c.o['key']]['map_progress_fact']['source'],'current_clipped_stage_clear')

    def add_accepted_message(self):
        c = self.c
        from story_open_ack import digest
        t = c.start.timestamp()
        action = '补发尚未响应的免费观看入口 '+c.o['key']+' #1'
        observations = []
        for i, offset in enumerate((.2, .4)):
            path = c.root/'evidence'/('message-'+str(i)+'.png')
            path.write_bytes(runner.cv2.imencode('.png', c.f.image)[1].tobytes())
            observations.append(dict(captured_at=t+offset, binding=c.binding,
                map=dict(key=c.o['key'], locked=False, clear_badge=False, star_count=None),
                target=dict(text='观看故事', score=.999, x=1390, y=827),
                image_sha256=hashlib.sha256(c.f.image.tobytes()).hexdigest(), evidence=str(path.relative_to(c.root))))
        message = dict(id='valid-message', action=action, status='sent', reserved_at=t+.5, sent_at=t+.8,
            observations=observations, source=dict(original_dispatch_id=c.dispatch['id'],
            original_sha256=c.dispatch['original_sha256'], events_sha256=digest(c.events[:1])))
        c.ack['messages'] = [message]
        c.events.insert(1, dict(kind='action', action=action, stage=c.o['key'], time=c.events[0]['time']))
        return message

    def test_accepted_original_message_chain_is_not_mistaken_for_replay(self):
        self.add_accepted_message()
        proof = self.read()
        self.assertIsNotNone(proof)
        self.assertEqual(proof['opening_message_receipts'][0]['message_id'], 'valid-message')
        self.assertFalse(proof['clickable'])

    def test_unknown_failed_changed_or_unproved_message_cannot_claim_a_result(self):
        c = self.c
        message = self.add_accepted_message()
        original = copy.deepcopy(message)
        for mode in ('unknown', 'not_sent', 'source', 'pixels', 'time', 'target'):
            with self.subTest(mode=mode):
                c.ack['messages'][0] = copy.deepcopy(original)
                message = c.ack['messages'][0]
                if mode in ('unknown', 'not_sent'):
                    message['status'] = mode
                elif mode == 'source':
                    message['source']['events_sha256'] = 'changed'
                elif mode == 'pixels':
                    message['observations'][0]['image_sha256'] = 'changed'
                elif mode == 'time':
                    message['sent_at'] = c.ack['accepted_at']+10
                else:
                    message['observations'][0]['target']['text'] = '购买'
                self.assertIsNone(self.read())

    def test_current_unknown_overlay_still_vetoes_any_underlying_result(self):
        self.c.f.words.append(dict(text='点击关闭', score=.99, x=800, y=600, box=[]))
        self.assertIsNone(self.read())


if __name__ == '__main__':
    unittest.main()
