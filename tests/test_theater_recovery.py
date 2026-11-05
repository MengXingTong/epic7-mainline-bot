"""Human-authorized single ticket recovery; originals never cleared or relabeled."""
import copy
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from abyss_core import Observation, Token
from assistant_worker import StopRun
from entry_journal import can_enter
from pc_backend import InputDeliveryError
from task_blockers import TaskAttention
from theater_core import Episode, Reading, classify, plan
from theater_journal import TheaterJournal, TICKET_RECOVERY_KEY, ticket_recovery_permission
from test_theater_ticket import immediate_dialog
import test_theater as helpers

TARGET = dict(client='pc', hwnd=1, pid=2, created=3, exe='fake.exe', title='test')


def directory():
    return Reading('theater_list', helpers.token('进行观览', 1400, 805), Episode('没落大地', 9, 1),
                   ticket_cost=1, ticket_stock=10)


class TicketRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        old = TheaterJournal(self.root, 'old')
        record = old.reserve('open', directory(), 'original.png'); old.finish(record, 'sent')
        self.journal = TheaterJournal(self.root, 'current')
        self.original = copy.deepcopy(self.journal.state)

    def authorize(self):
        return self.journal.authorize_pending_ticket_recovery(directory(), 'fresh.png', 'User explicitly approved this one pending ticket', TARGET)

    def protected_unchanged(self):
        for key in ('attempted', 'completed', 'entry_dispatches', 'unresolved_entries', 'last_cleared'):
            self.assertEqual(self.journal.state[key], self.original[key], key)
        self.assertFalse(can_enter(self.journal.state, TICKET_RECOVERY_KEY))

    def test_default_still_blocks_old_attempt_without_explicit_grant(self):
        with self.assertRaises(TaskAttention):plan(directory(), self.journal.state, 'current')
        self.assertIsNone(ticket_recovery_permission(self.journal.state, directory()))
        self.protected_unchanged()

    def test_authorization_appends_no_rewrite_and_is_one_use(self):
        grant = self.authorize(); self.protected_unchanged()
        self.assertEqual(plan(directory(), self.journal.state, 'current'), 'recover_open')
        record = self.journal.reserve('recover_open', directory(), 'fresh2.png')
        self.assertEqual(grant['status'], 'reserved'); self.protected_unchanged()
        self.assertIsNone(ticket_recovery_permission(self.journal.state, directory()))
        with self.assertRaises(TaskAttention):self.journal.reserve('recover_open', directory(), 'repeated.png')
        self.journal.finish(record, 'sent')
        self.assertEqual(self.journal.state['active']['phase'], 'await_ticket')
        self.assertEqual(grant['status'], 'sent'); self.protected_unchanged()
        ticket = classify(immediate_dialog())
        self.assertEqual(plan(ticket, self.journal.state, 'current'), 'ticket')
        record = self.journal.reserve('ticket', ticket, 'ticket.png'); self.journal.finish(record, 'sent')
        with self.assertRaises(TaskAttention):plan(ticket, self.journal.state, 'current')
        self.protected_unchanged()

    def test_other_episode_season_title_or_stock_cost_never_authorized(self):
        self.authorize()
        for r in (replace(directory(), episode=Episode('没落大地', 10, 1)),
                  replace(directory(), episode=Episode('没落大地', 9, 2)),
                  replace(directory(), episode=Episode('其他剧目', 9, 1)),
                  replace(directory(), ticket_cost=2), replace(directory(), ticket_stock=9),
                  replace(directory(), ticket_stock=None), replace(directory(), completed=(9,))):
            self.assertIsNone(ticket_recovery_permission(self.journal.state, r))
        self.protected_unchanged()

    def test_no_auto_grant_other_episode_or_implicit_authorization(self):
        for reason, target, reading in (('', TARGET, directory()), ('explicit', {'client':'pc'}, directory()),
                                       ('explicit', TARGET, replace(directory(), episode=Episode('没落大地', 10, 1)))):
            with self.assertRaises(TaskAttention):self.journal.authorize_pending_ticket_recovery(reading, 'x.png', reason, target)
        self.assertNotIn('pending_ticket_recoveries', self.journal.state)

    def test_original_hash_mutation_invalidates_unused_grant(self):
        self.authorize()
        for field in ('attempted', 'unresolved_entries', 'actions', 'entry_dispatches'):
            saved = copy.deepcopy(self.journal.state[field])
            if field == 'attempted':self.journal.state[field][TICKET_RECOVERY_KEY]['extra'] = 'changed'
            elif field == 'unresolved_entries':self.journal.state[field][0]['reason'] = 'changed'
            elif field == 'actions':self.journal.state[field][0]['status'] = 'reserved'
            else:self.journal.state[field][TICKET_RECOVERY_KEY][0]['reason'] = 'changed'
            self.assertIsNone(ticket_recovery_permission(self.journal.state, directory()), field)
            self.journal.state[field] = saved

    def test_expired_and_future_authorization_and_duplicate_grants_block(self):
        grant = self.authorize()
        with patch('theater_journal.time.time', return_value=grant['expires_at']+1):
            self.assertIsNone(ticket_recovery_permission(self.journal.state, directory()))
        with patch('theater_journal.time.time', return_value=grant['authorized_at']-1):
            self.assertIsNone(ticket_recovery_permission(self.journal.state, directory()))
        self.journal.state['pending_ticket_recoveries'].append(copy.deepcopy(grant))
        self.assertIsNone(ticket_recovery_permission(self.journal.state, directory()))

    def test_ticket_reserved_sent_not_sent_or_playback_blocks_new_grant(self):
        original = copy.deepcopy(self.journal.state)
        for status in ('reserved', 'sent', 'not_sent'):
            self.journal.state = copy.deepcopy(original)
            self.journal.state['actions'].append(dict(kind='ticket', key=TICKET_RECOVERY_KEY, status=status))
            with self.assertRaises(TaskAttention):self.authorize()
        for phase in ('failed', 'await_guide', 'story'):
            self.journal.state = copy.deepcopy(original)
            self.journal.state['unresolved_entries'][0]['entry']['phase'] = phase
            with self.assertRaises(TaskAttention):self.authorize()
        self.journal.state = copy.deepcopy(original)
        self.journal.state['unresolved_entries'][0]['entry']['playback_evidence'] = 'played.png'
        with self.assertRaises(TaskAttention):self.authorize()

    def test_completed_legacy_attempt_or_ambiguous_archive_blocks_grant(self):
        original = copy.deepcopy(self.journal.state)
        for mode in ('completed', 'legacy', 'archive'):
            self.journal.state = copy.deepcopy(original)
            if mode == 'completed':self.journal.state['completed'][TICKET_RECOVERY_KEY] = {'proof':'clear.png'}
            elif mode == 'legacy':self.journal.state['attempted']['没落大地|episode:9'] = {'old':'unknown'}
            else:self.journal.state['unresolved_entries'].append(copy.deepcopy(self.journal.state['unresolved_entries'][0]))
            with self.assertRaises(TaskAttention):self.authorize()

    def test_recovery_error_or_not_sent_never_recycles_authorization(self):
        self.authorize()
        record = self.journal.reserve('recover_open', directory(), 'fresh2.png')
        self.journal.finish(record, 'not_sent', 'definitely not pressed')
        self.assertIsNone(ticket_recovery_permission(self.journal.state, directory()))
        with self.assertRaises(TaskAttention):self.authorize()
        self.protected_unchanged()

    def test_unknown_dispatch_survives_new_run_without_reopen(self):
        self.authorize(); self.journal.reserve('recover_open', directory(), 'fresh2.png')
        restarted = TheaterJournal(self.root, 'next')
        self.assertEqual(restarted.state['pending_ticket_recoveries'][0]['status'], 'reserved')
        self.assertIsNone(ticket_recovery_permission(restarted.state, directory()))
        with self.assertRaises(TaskAttention):plan(directory(), restarted.state, 'next')
        self.assertEqual(restarted.state['attempted'], self.original['attempted'])

    def test_recovery_ticket_inventory_must_still_match_and_guide_chain_not_skipped(self):
        self.authorize(); record=self.journal.reserve('recover_open', directory(), 'fresh2.png'); self.journal.finish(record, 'sent')
        for stock in (9, 11):
            with self.assertRaises(TaskAttention):plan(classify(immediate_dialog(stock=stock)), self.journal.state, 'current')
        with self.assertRaises(TaskAttention):plan(classify(helpers.guide()), self.journal.state, 'current')
        with self.assertRaises(TaskAttention):plan(classify(immediate_dialog()), self.journal.state, 'wrong_run')

    def run_worker(self, *, target=None, send_error=False, save_error=False):
        from theater_worker import run
        self.authorize()
        ctl=Mock();ctl.attention.side_effect=StopRun()
        im=Image.new('RGB',(1600,900),'#333333')
        transport=Mock();transport.ensure.return_value='same_window'
        transport.capture.side_effect=[SimpleNamespace(image=im, captured_at=time.monotonic()) for _ in range(3)]+[StopRun()]
        if send_error:transport.tap.side_effect=InputDeliveryError('unknown send')
        request=dict(run_id='current', settings={'observe':False,'task':'theater'}, target=target or TARGET)
        observations=iter([helpers.observation(),immediate_dialog(),helpers.guide()])
        vision=Mock();vision.apply.side_effect=lambda im,o:o
        actual_classify=classify
        readings=iter([directory(), actual_classify(immediate_dialog()), actual_classify(helpers.guide())])
        with patch('assistant_config.validate_run',return_value=(self.root,{})),patch('assistant_transport.UnifiedTransport',return_value=transport),patch('rapidocr_onnxruntime.RapidOCR'),patch('theater_worker.TheaterVision',return_value=vision),patch('theater_worker.read_observation',side_effect=lambda *args:next(observations)),patch('theater_worker.classify',side_effect=lambda o:next(readings)),patch('assistant_worker.wait_for_input',return_value=False):
            writer=patch('theater_journal.durable_json',side_effect=OSError('disk full')) if save_error else patch('theater_worker.STORY_PRESS_SECONDS',.01)
            with writer:
                with self.assertRaises((StopRun,InputDeliveryError,OSError)):run(request,ctl)
        state=json.loads(self.journal.path.read_text(encoding='utf-8'))
        return transport,ctl,state

    def test_worker_recovery_open_ticket_guide_are_single_send_with_original_entry(self):
        transport,ctl,state=self.run_worker()
        self.assertEqual(transport.tap.call_count,3);ctl.attention.assert_not_called()
        self.assertEqual([a['kind'] for a in state['actions']], ['open','recover_open','ticket','guide'])
        self.assertEqual(state['active']['phase'],'story')
        for key in ('attempted','entry_dispatches','unresolved_entries','completed','last_cleared'):
            self.assertEqual(state[key],self.original[key])

    def test_worker_target_change_before_claim_never_sends(self):
        transport,ctl,state=self.run_worker(target={**TARGET,'pid':999})
        transport.tap.assert_not_called();ctl.attention.assert_called_once()
        self.assertEqual(state['pending_ticket_recoveries'][0]['status'],'authorized')

    def test_worker_send_error_retains_consumed_unknown_intent(self):
        transport,ctl,state=self.run_worker(send_error=True)
        transport.tap.assert_called_once()
        self.assertEqual(state['pending_ticket_recoveries'][0]['status'],'reserved')
        self.assertEqual(state['actions'][-1]['kind'],'recover_open')
        self.assertEqual(state['actions'][-1]['status'],'reserved')

    def test_worker_critical_write_failure_sends_zero_input(self):
        transport,ctl,state=self.run_worker(save_error=True)
        transport.tap.assert_not_called()
        self.assertEqual(state['pending_ticket_recoveries'][0]['status'],'authorized')
