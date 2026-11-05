"""Exact immediate-view ticket modal and transition regressions; no live input."""
import copy
import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from abyss_core import Observation, Token
from task_blockers import TaskAttention
from theater_core import classify, plan
from theater_journal import TheaterJournal
import test_theater as helpers


def immediate_dialog(cost=1, stock=10):
    # Synthetic reference geometry; no account data or production fixture.
    return helpers.observation([
        helpers.token('使用剧场门票', 800, 190),
        helpers.token('距离免费观览还剩6天。', 800, 288),
        helpers.token(f'确定要使用{cost}张剧场门票来立即观览吗？', 800, 314),
        helpers.token('入场券', 840, 396),
        helpers.token('剧场门票', 860, 430),
        helpers.token(f'持有：{stock}', 735, 500),
        helpers.token('※观览中无法跳过。', 800, 560),
        helpers.token('取消', 668, 660),
        helpers.token('确认', 928, 660),
    ])


class ImmediateTicketTests(unittest.TestCase):
    def test_complete_question_separated_from_countdown_item_and_inventory(self):
        r = classify(immediate_dialog())
        self.assertEqual(r.scene, 'theater_ticket')
        self.assertEqual((r.ticket_cost, r.ticket_stock), (1, 10))
        self.assertEqual(r.target.center, (928, 660))

    def test_native_and_half_geometry_use_their_own_current_frame_target(self):
        for width, height in ((1154, 649), (800, 450)):
            o = immediate_dialog()
            o.tokens = [replace(t, x=t.x*width/1600, w=t.w*width/1600,
                                y=t.y*height/900, h=t.h*height/900) for t in o.tokens]
            o.width, o.height = width, height
            r = classify(o)
            self.assertEqual(r.scene, 'theater_ticket')
            self.assertEqual(r.target, o.tokens[-1])

    def test_cost_not_inferred_from_stock_or_title(self):
        for cost in (0, 2, 10):
            self.assertNotEqual(classify(immediate_dialog(cost, stock=1)).scene, 'theater_ticket')
        o = immediate_dialog(); o.tokens.pop(2)
        self.assertEqual(classify(o).scene, 'theater_unknown_dialog')

    def test_missing_weak_duplicate_and_misplaced_fields_block(self):
        for index in (0, 2, 5, 7, 8):
            with self.subTest(index=index):
                o = immediate_dialog(); o.tokens.pop(index)
                self.assertNotEqual(classify(o).scene, 'theater_ticket')
                o = immediate_dialog(); o.tokens[index] = replace(o.tokens[index], score=.4)
                self.assertNotEqual(classify(o).scene, 'theater_ticket')
                o = immediate_dialog(); o.tokens.append(o.tokens[index])
                self.assertNotEqual(classify(o).scene, 'theater_ticket')
                o = immediate_dialog(); o.tokens[index] = replace(o.tokens[index], y=10)
                self.assertNotEqual(classify(o).scene, 'theater_ticket')

    def test_zero_malformed_or_unknown_inventory_never_spends(self):
        for stock in (0, '?', '10/20', '-1'):
            self.assertNotEqual(classify(immediate_dialog(stock=stock)).scene, 'theater_ticket')
        self.assertEqual(classify(immediate_dialog(stock=0)).scene, 'theater_blocked')

    def test_resource_defeat_unknown_cost_still_veto(self):
        for text in ('购买门票', '兑换', '额外消耗', '其他道具', '金币1000', '战斗失败'):
            o = immediate_dialog(); o.tokens.append(helpers.token(text, 800, 450, score=.3))
            self.assertNotEqual(classify(o).scene, 'theater_ticket', text)

    def test_exact_question_not_substring_or_ambiguous_action(self):
        for text in ('确定要使用1张剧场门票来立即观览吗？额外扣费',
                     '确定要使用1张剧场门票来观览吗？',
                     '确定要使用1张剧场门票来立即观览'):
            o = immediate_dialog(); o.tokens[2] = replace(o.tokens[2], text=text)
            self.assertNotEqual(classify(o).scene, 'theater_ticket')
        o = immediate_dialog(); o.tokens.append(helpers.token('改用其他道具消耗', 800, 314, score=.4))
        self.assertNotEqual(classify(o).scene, 'theater_ticket')

    def test_ticket_still_requires_same_run_await_ticket_chain(self):
        r = classify(immediate_dialog())
        for active in (None, {'run_id': 'old', 'phase': 'await_ticket'},
                       {'run_id': 'test', 'phase': 'await_guide'}):
            with self.assertRaises(TaskAttention):plan(r, {'active': active}, 'test')
        self.assertEqual(plan(r, {'active': {'run_id': 'test', 'phase': 'await_ticket'}}, 'test'), 'ticket')

    def test_simulated_flow_only_one_ticket_no_completion_fabrication(self):
        transport, ctl, state = helpers.TheaterWorkerTests().run_frames([
            helpers.listing(), immediate_dialog(), immediate_dialog(), helpers.guide(),
            helpers.observation(visuals=['theater_story'])])
        self.assertEqual(transport.tap.call_count, 4)
        self.assertEqual(len([r for r in state['actions'] if r['kind'] == 'ticket']), 1)
        self.assertEqual(state['active']['phase'], 'story')
        self.assertEqual(state['completed'], {})
        ctl.attention.assert_not_called()

    def test_partial_dialog_observed_without_input_then_first_complete_frame_acts(self):
        partial = immediate_dialog(); partial.tokens.pop(2)
        transport, ctl, state = helpers.TheaterWorkerTests().run_frames([
            helpers.listing(), partial, partial, immediate_dialog()], processing_seconds=.001)
        self.assertEqual(transport.tap.call_count, 2)
        self.assertEqual(state['active']['phase'], 'await_guide')
        ctl.attention.assert_not_called()
        self.assertTrue(any(c.kwargs.get('mode') == 'waiting_scene' for c in ctl.status.call_args_list))

    def test_stable_unknown_dialog_eventually_waits_for_user_with_zero_input(self):
        partial = immediate_dialog(); partial.tokens.pop(2)
        transport, ctl, state = helpers.TheaterWorkerTests().run_frames([partial]*19, processing_seconds=.001)
        transport.tap.assert_not_called()
        ctl.attention.assert_called_once()
        self.assertEqual(ctl.attention.call_args.args[0].code, 'theater_unknown_dialog')
        self.assertEqual(state['attempted'], {})

    def test_changing_unknown_dialog_keeps_zero_input(self):
        frames = []
        for index in range(19):
            partial = immediate_dialog(); partial.tokens.pop(2)
            partial.tokens.append(helpers.token('未加载通知'+str(index), 800, 430))
            frames.append(partial)
        transport, ctl, _ = helpers.TheaterWorkerTests().run_frames(frames, processing_seconds=.001)
        transport.tap.assert_not_called(); ctl.attention.assert_not_called()

    def test_same_run_reload_retains_open_sent_chain_without_reopening(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = TheaterJournal(folder, 'test')
            r = classify(helpers.listing())
            dispatch = journal.reserve('open', r, 'open.png'); journal.finish(dispatch, 'sent')
            before = copy.deepcopy(journal.state)
            reloaded = TheaterJournal(folder, 'test')
            self.assertEqual(reloaded.state, before)
            r = classify(immediate_dialog())
            dispatch = reloaded.reserve(plan(r, reloaded.state, 'test'), r, 'ticket.png')
            reloaded.finish(dispatch, 'sent')
            self.assertEqual(reloaded.state['attempted'], before['attempted'])
            self.assertEqual(reloaded.state['entry_dispatches'], before['entry_dispatches'])
            self.assertEqual([a['kind'] for a in reloaded.state['actions']], ['open', 'ticket'])
            self.assertEqual(reloaded.state['active']['phase'], 'await_guide')

    def test_sent_ticket_history_survives_restart_and_does_not_reauthorize(self):
        with tempfile.TemporaryDirectory() as folder:
            journal = TheaterJournal(folder, 'test')
            r = classify(helpers.listing())
            dispatch = journal.reserve('open', r, 'open.png'); journal.finish(dispatch, 'sent')
            r = classify(immediate_dialog())
            dispatch = journal.reserve(plan(r, journal.state, 'test'), r, 'ticket.png')
            journal.finish(dispatch, 'sent')
            attempted = copy.deepcopy(journal.state['attempted'])
            with self.assertRaises(TaskAttention):plan(r, journal.state, 'test')
            restarted = TheaterJournal(folder, 'new')
            self.assertEqual(restarted.state['attempted'], attempted)
            self.assertEqual(restarted.state['completed'], {})
            self.assertEqual(restarted.state['unresolved_entries'][0]['entry']['phase'], 'await_guide')
            with self.assertRaises(TaskAttention):plan(r, restarted.state, 'new')

    def test_saved_private_ticket_modal_readonly_replay(self):
        path = Path(__file__).resolve().parents[1]/'.local/theater-ticket-20261104/dialog.json'
        if not path.is_file():self.skipTest('未分发真实剧场私有画面')
        m = json.loads(path.read_text(encoding='utf-8'))
        o = Observation(m['width'], m['height'], [Token(**t) for t in m['tokens']])
        r = classify(o)
        self.assertEqual(r.scene, 'theater_ticket')
        self.assertEqual((r.ticket_cost, r.ticket_stock), (1, 10))
        self.assertIn(r.target, o.tokens)
        self.assertIsNone(r.episode)
