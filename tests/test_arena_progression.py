"""Current-frame arena progression; all captures, inputs and files are synthetic."""
import contextlib
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from abyss_core import Observation, Token
from arena_core import Reading
from arena_journal import ArenaJournal
from assistant_config import read_json
from assistant_transport import FrameSnapshot
from assistant_worker import StopRun
from pc_backend import PcSafetyError, TapNotSent
from task_blockers import TaskAttention
import arena_worker


def token(text, x, y, score=.999):
    return Token(text, x*1600-10, y*900-8, 20, 16, score=score)


def npc(challenge=False, name='NPC A'):
    words = [token('新手竞技场', .10, .05), token('NPC交战对手', .30, .16),
             token('NPC对战', .87, .30), token(name, .4, .315)]
    if challenge:
        words.append(token('挑战', .5, .92))
    return Observation(1600, 900, words, visuals={'arena_npc_first_selected','arena_challenge_enabled'} if challenge else set())


def team(cost='1/12', name='NPC A'):
    return Observation(1600, 900, [token('新手竞技场', .10, .05),
        token('战斗开始', .66, .92), token('NPC对战', .69, .77),
        token(name, .70, .71), token(cost, .58, .92)])


def battle(auto=True, name='NPC A'):
    return Observation(1600, 900, [token(name, .6, .085), token('A', .88, .05)],
        visuals={'arena_pause', 'arena_hp_left', 'arena_hp_right',
                 'arena_auto_white' if auto else 'arena_auto_on'})


def result(name='NPC A'):
    return Observation(1600, 900, [token('VICTORY', .5, .35),
        token('战斗结果', .78, .92), token('确认', .915, .92),
        token('NPC对战的胜负', .50, .64), token('不会影响积分。', .5, .67),
        token(name, .6, .085)])


class Control:
    def __init__(self):
        self.statuses = []
        self.attentions = []
    def check(self): pass
    def preview(self, image): pass
    def status(self, *args, **kwargs): self.statuses.append((args, kwargs))
    def sleep(self, seconds): pass
    def attention(self, exc):
        self.attentions.append(exc)
        raise StopRun()
    def paused(self): pass


class ArenaProgressionTests(unittest.TestCase):
    def exercise(self, rows, requested=1, fail_on=None, patches=(), bindings=None,
                 timestamps=None, expect_error=None, prepare=None, initial_binding="window", maintenance_source=None):
        from PIL import Image
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        if prepare:
            prepare(root)
        control = Control()
        owner = self
        class Transport:
            def __init__(self):
                self.index = 0
                self.inputs = []
                self.ensure_calls = 0
                self.current = None
                self.started = time.monotonic()
            def ensure(self):
                self.ensure_calls += 1
                return initial_binding
            def capture(self):
                if self.index >= len(rows):
                    raise StopRun()
                self.current = rows[self.index]
                at = timestamps[self.index] if timestamps else self.started + self.index * .01
                binding = bindings[self.index] if bindings else 'window'
                self.index += 1
                return FrameSnapshot(Image.new('RGB', (1600, 900)), binding, at)
            def back(self, snap):
                self.tap(snap, token('原生返回', .03, .04))
            def tap(self, snap, target):
                # Each button-down must have durable current-frame intent/evidence.
                state = read_json(root/'arena/state.json')
                action = state['actions'][-1]
                owner.assertEqual(action['status'], 'reserved')
                owner.assertEqual(action['evidence']['captured_at'], snap.captured_at)
                for field, digest in [('image', 'image_sha256'), ('metadata', 'metadata_sha256')]:
                    data = (root/'arena'/action['evidence'][field]).read_bytes()
                    owner.assertEqual(hashlib.sha256(data).hexdigest(), action['evidence'][digest])
                owner.assertNotIn(self.index, [v[0] for v in self.inputs])
                self.inputs.append((self.index, action['kind'], target.text))
                if action['kind'] == 'entry':
                    owner.assertIsNotNone(state['active'])
                    owner.assertEqual(len(state['entry_dispatches'][action['key']]), 1)
                if fail_on == action['kind']:
                    raise TapNotSent('cancelled before down')
                if fail_on == 'unknown_' + action['kind']:
                    raise RuntimeError('send uncertain')
        tr = Transport()
        req = dict(run_id='current-frame', settings=dict(arena_count=requested), target={})
        if maintenance_source:req['arena_maintenance']=maintenance_source
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('assistant_config.validate_run', return_value=(root, {})))
            stack.enter_context(patch('assistant_transport.UnifiedTransport', return_value=tr))
            stack.enter_context(patch('rapidocr_onnxruntime.RapidOCR', return_value=object()))
            stack.enter_context(patch('arena_worker.read_observation', side_effect=lambda *a: tr.current))
            stack.enter_context(patch('arena_worker.ObservationCycle'))
            for manager in patches:
                stack.enter_context(manager)
            if expect_error:
                with self.assertRaises(expect_error):
                    arena_worker.run(req, control)
            else:
                try:
                    arena_worker.run(req, control)
                except StopRun:
                    pass
        return tr, control, read_json(root/'arena/state.json'), root

    def test_known_navigate_select_challenge_entry_use_first_current_frame(self):
        lobby = Observation(1600, 900, [token('竞技场', .92, .54),
            token('Episode', .9, .25), token('英雄', .75, .95)])
        tr, _, state, _ = self.exercise([lobby, npc(), npc(True), team()])
        self.assertEqual([(i, kind) for i, kind, _ in tr.inputs],
                         [(1, 'navigate'), (2, 'select'), (3, 'challenge'), (4, 'entry')])
        self.assertEqual(len(state['attempted']), 1)
        self.assertEqual(tr.ensure_calls, 1)  # capture's pre/post checks remain in the adapter

    def test_one_result_frame_completes_and_closes_then_one_list_frame_finishes(self):
        tr, control, state, _ = self.exercise([npc(), npc(True), team(), battle(), result(), npc()])
        self.assertEqual([(i, kind) for i, kind, _ in tr.inputs],
            [(1, 'select'), (2, 'challenge'), (3, 'entry'), (4, 'auto'), (5, 'result_close')])
        self.assertEqual(control.statuses[-1][1]['mode'], 'done')
        self.assertEqual(state['runs']['current-frame']['wins'], 1)
        self.assertIsNone(state['runs']['current-frame']['pending_result'])
        completed = next(iter(state['completed'].values()))
        self.assertLess(completed['battle_evidence']['captured_at'], completed['result_evidence']['captured_at'])
        self.assertLess(completed['result_evidence']['captured_at'], completed['close_evidence']['captured_at'])
        close = next(a for a in state['actions'] if a['kind'] == 'result_close')
        self.assertEqual(close['evidence'], completed['result_evidence'])

    def test_two_rounds_use_five_frames_each_plus_final_list_no_extra_entry(self):
        rows = [npc(), npc(True), team(), battle(), result(),
                npc(), npc(True), team(), battle(), result(), npc()]
        tr, control, state, _ = self.exercise(rows, requested=2)
        self.assertEqual(tr.index, 11)
        self.assertEqual([i for i, kind, _ in tr.inputs if kind == 'select'], [1, 6])
        self.assertEqual([i for i, kind, _ in tr.inputs if kind == 'entry'], [3, 8])
        self.assertEqual(len(state['attempted']), 2)
        self.assertEqual(len(state['completed']), 2)
        self.assertEqual(control.statuses[-1][1]['mode'], 'done')
        self.assertTrue(all(v.get('close_evidence') for v in state['completed'].values()))

    def test_repeated_team_after_sent_never_resends_entry(self):
        tr, _, state, _ = self.exercise([npc(), npc(True), team(), team(), team()])
        self.assertEqual([kind for _, kind, _ in tr.inputs], ['select', 'challenge', 'entry'])
        self.assertEqual(len(state['entry_dispatches']), 1)
        self.assertFalse(state['completed'])

    def test_repeated_battle_never_toggles_auto_twice(self):
        tr, _, state, _ = self.exercise([npc(), npc(True), team(), battle(), battle(), battle()])
        self.assertEqual(sum(kind == 'auto' for _, kind, _ in tr.inputs), 1)
        self.assertFalse(state['completed'])

    def test_repeated_result_never_recloses_or_recounts(self):
        tr, _, state, _ = self.exercise([npc(), npc(True), team(), battle(), result(), result(), result()])
        self.assertEqual(sum(kind == 'result_close' for _, kind, _ in tr.inputs), 1)
        self.assertEqual(len(state['completed']), 1)
        self.assertIsNotNone(state['runs']['current-frame']['pending_result'])

    def test_unknown_modal_does_not_acknowledge_or_start_next_round(self):
        overlay = npc()
        overlay.visuals.add('arena_notice_modal')
        tr, _, state, _ = self.exercise([npc(), npc(True), team(), battle(), result(), overlay], requested=2)
        self.assertEqual(sum(kind == 'select' for _, kind, _ in tr.inputs), 1)
        self.assertIsNotNone(state['runs']['current-frame']['pending_result'])
        self.assertNotIn('close_evidence', next(iter(state['completed'].values())))

    def test_missing_victory_field_keeps_observing_without_count_or_close(self):
        weak = result()
        weak.tokens.pop(0)
        tr, _, state, _ = self.exercise([npc(), npc(True), team(), battle(), weak])
        self.assertEqual(sum(kind == 'result_close' for _, kind, _ in tr.inputs), 0)
        self.assertFalse(state['completed'])
        self.assertIsNotNone(state['active'])

    def test_resources_capacity_and_defeat_still_preempt_known_controls(self):
        for label in ('购买挑战书', '挑战书不足', '装备背包已满', '战斗失败'):
            with self.subTest(label=label):
                blocked = team()
                blocked.tokens.append(token(label, .5, .5))
                tr, control, state, _ = self.exercise([npc(), npc(True), blocked])
                self.assertEqual([kind for _, kind, _ in tr.inputs], ['select', 'challenge'])
                self.assertTrue(control.attentions)
                self.assertFalse(state['attempted'])

    def test_other_opponent_result_cannot_complete_or_close(self):
        tr, control, state, _ = self.exercise([npc(), npc(True), team(), battle(), result('NPC B')])
        self.assertEqual(control.attentions[-1].code, 'arena_opponent')
        self.assertFalse(state['completed'])
        self.assertFalse(any(kind == 'result_close' for _, kind, _ in tr.inputs))

    def test_entry_not_sent_preserves_original_attempt_and_dispatch(self):
        tr, control, state, _ = self.exercise([npc(), npc(True), team()], fail_on='entry')
        self.assertEqual(control.attentions[-1].code, 'arena_not_sent')
        self.assertEqual(len(state['attempted']), 1)
        dispatch = next(iter(state['entry_dispatches'].values()))
        self.assertEqual(dispatch[0]['status'], 'not_sent')
        self.assertEqual(sum(kind == 'entry' for _, kind, _ in tr.inputs), 1)

    def test_uncertain_entry_preserves_unknown_without_retry(self):
        tr, _, state, _ = self.exercise([npc(), npc(True), team()],
            fail_on='unknown_entry', expect_error=RuntimeError)
        self.assertEqual(next(iter(state['entry_dispatches'].values()))[0]['status'], 'unknown')
        self.assertEqual(len(state['attempted']), 1)
        self.assertFalse(state['completed'])

    def test_changed_capture_binding_stops_before_recognition_or_input(self):
        read = Mock(side_effect=AssertionError('must not recognize another window'))
        tr, _, state, _ = self.exercise([npc()], bindings=['other-window'],
            patches=[patch('arena_worker.read_observation', read)], expect_error=PcSafetyError)
        self.assertFalse(tr.inputs)
        self.assertFalse(state['actions'])
        read.assert_not_called()

    def test_reused_capture_timestamp_stops_before_second_input(self):
        at = time.monotonic()
        tr, _, state, _ = self.exercise([npc(), npc(True)], timestamps=[at, at], expect_error=PcSafetyError)
        self.assertEqual([kind for _, kind, _ in tr.inputs], ['select'])
        self.assertEqual(len(state['actions']), 1)

    def test_mouse_wait_discards_plan_and_requires_a_new_current_frame(self):
        tr, _, state, _ = self.exercise([npc(), Observation(1600, 900, [])],
            patches=[patch('assistant_worker.wait_for_input', return_value=True)])
        self.assertFalse(tr.inputs)
        self.assertFalse(state['actions'])

    def test_intent_write_failure_prevents_entry_input(self):
        original = ArenaJournal.save
        def fail_entry(journal):
            if journal.state['actions'] and journal.state['actions'][-1]['kind'] == 'entry':
                raise OSError('disk full')
            return original(journal)
        tr, _, state, _ = self.exercise([npc(), npc(True), team()],
            patches=[patch.object(ArenaJournal, 'save', fail_entry)], expect_error=OSError)
        self.assertEqual([kind for _, kind, _ in tr.inputs], ['select', 'challenge'])
        self.assertFalse(state['attempted'])

    def test_complete_write_failure_prevents_result_close(self):
        original = ArenaJournal.save
        def fail_complete(journal):
            if journal.state['completed']:
                raise OSError('cannot persist victory')
            return original(journal)
        tr, _, state, _ = self.exercise([npc(), npc(True), team(), battle(), result()],
            patches=[patch.object(ArenaJournal, 'save', fail_complete)], expect_error=OSError)
        self.assertFalse(any(kind == 'result_close' for _, kind, _ in tr.inputs))
        self.assertFalse(state['completed'])
        self.assertIsNotNone(state['active'])

    def test_unsent_result_close_preserves_pending_and_never_selects_next(self):
        tr, control, state, _ = self.exercise([npc(), npc(True), team(), battle(), result(), npc()],
            requested=2, fail_on='result_close')
        self.assertEqual(control.attentions[-1].code, 'arena_not_sent')
        self.assertEqual(state['runs']['current-frame']['wins'], 1)
        self.assertIsNotNone(state['runs']['current-frame']['pending_result'])
        self.assertEqual(sum(kind == 'select' for _, kind, _ in tr.inputs), 1)
        self.assertEqual(state['actions'][-1]['status'], 'not_sent')
        self.assertNotIn('close_evidence', next(iter(state['completed'].values())))

    def test_result_without_independent_battle_never_completes(self):
        tr, _, state, _ = self.exercise([npc(), npc(True), team(), result()], expect_error=ValueError)
        self.assertFalse(state['completed'])
        self.assertIsNotNone(state['active'])
        self.assertFalse(any(kind == 'result_close' for _, kind, _ in tr.inputs))

    def test_resource_count_is_rechecked_on_the_single_entry_frame(self):
        for cost in ('1/0', '2/12'):
            with self.subTest(cost=cost):
                tr, control, state, _ = self.exercise([npc(), npc(True), team(cost=cost)])
                self.assertEqual([kind for _, kind, _ in tr.inputs], ['select', 'challenge'])
                self.assertTrue(control.attentions)
                self.assertFalse(state['attempted'])

    def test_return_list_write_failure_prevents_next_select(self):
        def fail_ack(journal, *args):
            raise OSError('cannot persist close evidence')
        tr, _, state, _ = self.exercise([npc(), npc(True), team(), battle(), result(), npc()], requested=2,
            patches=[patch.object(ArenaJournal, 'acknowledge_close', fail_ack)], expect_error=OSError)
        self.assertEqual(sum(kind == 'select' for _, kind, _ in tr.inputs), 1)
        self.assertIsNotNone(state['runs']['current-frame']['pending_result'])


class ArenaResultFieldTests(unittest.TestCase):
    @staticmethod
    def rows(obs):
        return [([[t.x,t.y],[t.x+t.w,t.y],[t.x+t.w,t.y+t.h],[t.x,t.y+t.h]],t.text,t.score)
                for t in obs.tokens]

    def test_single_original_field_read_preserves_raw_name_and_threshold(self):
        from PIL import Image
        for text,score,accepted in [('NPC A',.991,True),('NPC A',.979,False),('NPC B',.999,False)]:
            with self.subTest(text=text,score=score):
                obs=result();original=obs.tokens[-1]
                obs.tokens[-1]=Token(original.text,original.x,original.y,original.w,original.h,score=.943)
                ocr=Mock(side_effect=[(self.rows(obs),None),([[text,score]],None)])
                read=arena_worker.read_observation(Image.new('RGB',(1600,900)),ocr,17)
                self.assertEqual(read.tokens[-2 if accepted else -1].score,.943)
                self.assertEqual(arena_worker.classify(read).scene,'arena_result' if accepted else 'arena_unknown')
                self.assertEqual(ocr.call_count,2)
                self.assertEqual(ocr.call_args.kwargs,dict(use_det=False,use_cls=False))
                self.assertEqual(ocr.call_args.args[0].shape[0],48)
                self.assertEqual(read.captured_at,17)
                if accepted:self.assertEqual(read.tokens[-1].source,'arena_result_name_field_read')

    def test_strong_result_name_does_not_run_supplement(self):
        from PIL import Image
        ocr=Mock(return_value=(self.rows(result()),None))
        read=arena_worker.read_observation(Image.new('RGB',(1600,900)),ocr,17)
        self.assertEqual(arena_worker.classify(read).scene,'arena_result')
        self.assertEqual(ocr.call_count,1)

    def test_missing_context_or_ambiguous_name_never_uses_field_fallback(self):
        from PIL import Image
        for condition in ('missing_confirm','duplicate_name','outside_field','too_weak'):
            with self.subTest(condition=condition):
                obs=result();original=obs.tokens[-1]
                obs.tokens[-1]=Token(original.text,original.x,original.y,original.w,original.h,score=.943)
                if condition=='missing_confirm':obs.tokens.pop(2)
                elif condition=='duplicate_name':obs.tokens.append(obs.tokens[-1])
                elif condition=='outside_field':
                    obs.tokens[-1]=Token(original.text,700,original.y,600,original.h,score=.943)
                else:obs.tokens[-1]=Token(original.text,original.x,original.y,original.w,original.h,score=.89)
                ocr=Mock(return_value=(self.rows(obs),None))
                arena_worker.read_observation(Image.new('RGB',(1600,900)),ocr,17)
                self.assertEqual(ocr.call_count,1)

    def test_ambiguous_field_response_is_not_supplemented(self):
        from PIL import Image
        obs=result();original=obs.tokens[-1]
        obs.tokens[-1]=Token(original.text,original.x,original.y,original.w,original.h,score=.943)
        for rows in ([],[['NPC A',.999],['NPC A',.999]]):
            ocr=Mock(side_effect=[(self.rows(obs),None),(rows,None)])
            read=arena_worker.read_observation(Image.new('RGB',(1600,900)),ocr,17)
            self.assertEqual(arena_worker.classify(read).scene,'arena_unknown')
            self.assertEqual(ocr.call_count,2)


if __name__ == '__main__':
    unittest.main()
