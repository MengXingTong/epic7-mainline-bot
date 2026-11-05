"""Already-open modal continuation: private explicit receipt, no second OPEN."""
import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image
from assistant_worker import StopRun
from entry_journal import attempt_digest, can_enter
from pc_backend import WindowSnapshot, TapNotSent, InputDeliveryError
from task_blockers import TaskAttention
from theater_core import classify, plan, Reading
from theater_journal import TheaterJournal, durable_json
from theater_pending_confirmation import (CONFIRMATION_KEY, RECEIPT_NAME, TARGET_FIELDS,
    attach_receipt, pending_source, ticket_permission, continued_opening, file_sha256)
from theater_worker import story_return_pending
from theater_vision import TheaterVision
from test_theater_directory import directory
from test_theater_ticket import immediate_dialog
import test_theater as h


class OpenConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.home = self.root/'home'; self.profile = self.root/'profile'
        self.profile.mkdir(); self.old = 'a'*32; self.run = 'b'*32
        self.binding = WindowSnapshot(1, 2, 'test.exe', 3, 10, 20, 1600, 900)
        self.target = dict(client='pc', hwnd=1, pid=2, created=3, exe='test.exe', title='test')
        self.folder = self.home/'runs'/self.run; self.folder.mkdir(parents=True)
        self.request = dict(run_id=self.run, run_dir=str(self.folder), home=str(self.home), target=self.target,
            settings=dict(task='theater', observe=False, pc_input='messages', data_dir=str(self.profile)))
        durable_json(self.folder/'request.json', self.request)
        old_folder = self.home/'runs'/self.old; old_folder.mkdir()
        durable_json(old_folder/'request.json', dict(self.request, run_id=self.old, run_dir=str(old_folder)))
        old = TheaterJournal(self.profile, self.old)
        image, obs = directory(selected=7, completed=(5,6), stock=7)
        self.obs = TheaterVision().apply(image, obs)
        self.obs.visuals.discard('theater_season:1'); self.obs.visuals.add('theater_season:2')
        self.reading = classify(self.obs)
        self.assertEqual(self.reading.episode.key, CONFIRMATION_KEY)
        proof = old.evidence(SimpleNamespace(image=image, captured_at=time.monotonic()), self.obs, self.reading)
        record = old.reserve('open', self.reading, proof); old.finish(record, 'sent')
        self.journal = TheaterJournal(self.profile, self.run)
        self.before = copy.deepcopy(self.journal.state)
        self.dialog = immediate_dialog(stock=7); self.ticket = classify(self.dialog)
        self.proof = self.journal.evidence(SimpleNamespace(image=image, captured_at=time.monotonic()), self.dialog, self.ticket)
        attempt, archive, opened = pending_source(self.journal.state)
        source = self.journal.root/attempt['evidence']
        self.receipt = dict(schema=1, id='c'*32, scope='continue_existing_open_ticket_once',
            key=CONFIRMATION_KEY, run_id=self.run, authorization='Explicit human approval for this pending modal only',
            authorized_at=time.time(), expires_at=time.time()+600, expected_stock=7,
            target=self.target, binding=asdict(self.binding), state_sha256=file_sha256(self.journal.path),
            request_sha256=file_sha256(self.folder/'request.json'), source_request_sha256=file_sha256(old_folder/'request.json'),
            source_image_sha256=file_sha256(source), source_metadata_sha256=file_sha256(source.with_suffix('.json')))
        for k,v in zip(('attempt_sha256','archive_sha256','open_sha256'), (attempt,archive,opened)):
            self.receipt[k] = attempt_digest(v)
        self.path = self.folder/RECEIPT_NAME
        self.write_receipt()

    def write_receipt(self):
        durable_json(self.path, self.receipt)

    def attach(self, **kwargs):
        return attach_receipt(self.journal, kwargs.get('request',self.request), kwargs.get('reading',self.ticket),
                              self.proof, kwargs.get('binding',self.binding))

    def assert_original(self):
        for key in ('attempted','entry_dispatches','unresolved_entries','last_cleared','completed'):
            self.assertEqual(self.journal.state[key], self.before[key], key)
        self.assertEqual(self.journal.state['actions'][:1], self.before['actions'])
        self.assertFalse(can_enter(self.journal.state, CONFIRMATION_KEY))

    def test_no_receipt_is_no_recovery_and_no_spending(self):
        self.path.unlink(); self.assertFalse(self.attach())
        self.assertEqual(self.journal.state, self.before)
        with self.assertRaises(TaskAttention):plan(self.ticket, self.journal.state, self.run)

    def test_attach_preserves_all_history_and_only_first_confirmation(self):
        self.assertTrue(self.attach()); self.assert_original()
        self.assertEqual(self.journal.state['active']['source_run_id'], self.old)
        self.assertEqual(plan(self.ticket,self.journal.state,self.run),'ticket')
        a=self.journal.reserve('ticket',self.ticket,self.proof)
        self.assertEqual(self.journal.state['open_ticket_continuations'][0]['status'],'reserved')
        self.assertIsNone(ticket_permission(self.journal.state,self.run,self.ticket))
        with self.assertRaises(TaskAttention):self.journal.reserve('ticket',self.ticket,self.proof)
        self.journal.finish(a,'sent'); self.assertFalse(self.attach())
        with self.assertRaises(TaskAttention):plan(self.ticket,self.journal.state,self.run)
        self.assertEqual([a['kind'] for a in self.journal.state['actions']],['open','ticket'])
        self.assert_original()

    def test_unknown_reserved_not_sent_and_error_never_reuse_permission(self):
        self.attach(); saved=copy.deepcopy(self.journal.state)
        for status in ('reserved','unknown','not_sent','sent'):
            self.journal.state=copy.deepcopy(saved)
            a=self.journal.reserve('ticket',self.ticket,self.proof)
            if status=='unknown':a['status']='unknown';self.journal.save()
            elif status!='reserved':self.journal.finish(a,status)
            self.assertFalse(self.attach())
            with self.assertRaises(TaskAttention):plan(self.ticket,self.journal.state,self.run)
            with self.assertRaises(TaskAttention):self.journal.reserve('ticket',self.ticket,self.proof)
            self.assert_original()

    def test_receipt_tampering_and_scope_stock_hash_target_time_all_deny_without_mutation(self):
        original=copy.deepcopy(self.receipt)
        changes={'key':'没落大地|season:2|episode:8','scope':'reopen','authorization':'','run_id':self.old,
            'id':'bad','expected_stock':8,'state_sha256':'bad','request_sha256':'bad',
            'source_request_sha256':'bad','source_image_sha256':'bad','source_metadata_sha256':'bad',
            'attempt_sha256':'bad','archive_sha256':'bad','open_sha256':'bad','authorized_at':time.time()+60,
            'expires_at':time.time()-1,'target':dict(self.target,pid=99),'binding':dict(asdict(self.binding),x=99)}
        for k,v in changes.items():
            with self.subTest(k=k):
                self.receipt={**copy.deepcopy(original),k:v}; self.write_receipt()
                raw=self.journal.path.read_bytes()
                with self.assertRaises(TaskAttention):self.attach()
                self.assertEqual(self.journal.state,self.before);self.assertEqual(raw,self.journal.path.read_bytes())

    def test_missing_or_changed_modal_and_geometry_or_current_run_deny(self):
        for r in (replace(self.ticket,scene='theater_unknown_dialog'),replace(self.ticket,ticket_cost=2),
                  replace(self.ticket,ticket_stock=6),replace(self.ticket,ticket_stock=None)):
            with self.assertRaises(TaskAttention):self.attach(reading=r)
        with self.assertRaises(TaskAttention):self.attach(binding=replace(self.binding,width=800))
        with self.assertRaises(TaskAttention):self.attach(request=dict(self.request,run_id=self.old))
        self.assertEqual(self.journal.state,self.before)

    def test_prior_payment_duplicate_failed_or_changed_source_never_attach(self):
        for mode in ('ticket','guide','play','unknown','duplicate','failed','completed','legacy'):
            with self.subTest(mode=mode):
                self.journal.state=copy.deepcopy(self.before);s=self.journal.state
                if mode in ('ticket','guide','play'):s['actions'].append(dict(s['actions'][0],kind=mode))
                elif mode=='unknown':s['actions'][0]['status']='unknown'
                elif mode=='duplicate':s['unresolved_entries'].append(copy.deepcopy(s['unresolved_entries'][0]))
                elif mode=='failed':s['unresolved_entries'][0]['entry']['phase']='failed'
                elif mode=='completed':s['completed'][CONFIRMATION_KEY]={'evidence':'bad'}
                else:s['attempted']['没落大地|episode:7']={}
                self.journal.save();self.receipt['state_sha256']=file_sha256(self.journal.path);self.write_receipt()
                snapshot=copy.deepcopy(s)
                with self.assertRaises(TaskAttention):self.attach()
                self.assertEqual(s,snapshot)

    def test_attached_stock_drift_expiry_or_source_mutation_denies_before_reservation(self):
        self.attach()
        for r in (replace(self.ticket,ticket_stock=6),replace(self.ticket,ticket_cost=2)):
            with self.assertRaises(TaskAttention):plan(r,self.journal.state,self.run)
        grant=self.journal.state['open_ticket_continuations'][0]
        with patch('theater_pending_confirmation.time.time',return_value=grant['expires_at']+1):
            with self.assertRaises(TaskAttention):plan(self.ticket,self.journal.state,self.run)
        self.journal.state['unresolved_entries'][0]['reason']='changed'
        with self.assertRaises(TaskAttention):plan(self.ticket,self.journal.state,self.run)
        self.assertEqual(len(self.journal.state['actions']),1)

    def test_paid_chain_return_and_independent_completion_without_reopen_or_forgery(self):
        self.attach();a=self.journal.reserve('ticket',self.ticket,self.proof);self.journal.finish(a,'sent')
        self.assertTrue(continued_opening(self.journal.state,self.run,self.before['actions'][0]))
        guide=classify(h.guide());self.assertEqual(plan(guide,self.journal.state,self.run),'guide')
        a=self.journal.reserve('guide',guide,'guide.png');self.journal.finish(a,'sent')
        self.journal.observe(Reading('theater_story'),'playback.png')
        self.assertTrue(story_return_pending(self.obs,self.reading,self.journal.state,self.run))
        self.assertFalse(story_return_pending(self.obs,self.reading,self.journal.state,self.old))
        self.assertEqual(self.journal.state['completed'],{})
        done=replace(self.reading,completed=(5,6,7))
        self.assertTrue(self.journal.observe(done,'independent-result.png'))
        self.assertIn(CONFIRMATION_KEY,self.journal.state['completed']);self.assertIsNone(self.journal.state['active'])
        self.assertFalse(self.attach());self.assertEqual(len(self.journal.state['entry_dispatches'][CONFIRMATION_KEY]),1)

    def run_worker(self,error=None,save_error=False):
        from theater_worker import run
        control=Mock();control.attention.side_effect=StopRun()
        transport=Mock();transport.ensure.return_value=self.binding
        image=Image.new('RGB',(1600,900),'#333333')
        transport.capture.side_effect=lambda:SimpleNamespace(image=image,captured_at=time.monotonic())
        def tap(*args,**kwargs):
            saved=json.loads(self.journal.path.read_text(encoding='utf-8'))
            self.assertEqual(saved['open_ticket_continuations'][0]['status'],'reserved')
            self.assertEqual(saved['actions'][-1]['status'],'reserved')
            if error:raise error
        transport.tap.side_effect=tap
        vision=Mock();vision.apply.side_effect=lambda im,o:o
        count=iter((self.dialog,StopRun()))
        def observation(*args):
            value=next(count)
            if isinstance(value,Exception):raise value
            return value
        writer=patch('theater_journal.durable_json',side_effect=OSError('disk full')) if save_error else patch('theater_worker.STORY_PRESS_SECONDS',.01)
        with patch('assistant_config.validate_run',return_value=(self.profile,{})),patch('assistant_transport.UnifiedTransport',return_value=transport),patch('rapidocr_onnxruntime.RapidOCR'),patch('theater_worker.TheaterVision',return_value=vision),patch('theater_worker.read_observation',side_effect=observation),patch('assistant_worker.wait_for_input',return_value=False),writer:
            with self.assertRaises((StopRun,InputDeliveryError,OSError)):run(self.request,control)
        return transport,json.loads(self.journal.path.read_text(encoding='utf-8'))

    def test_worker_consumes_permission_and_intent_durably_before_one_click(self):
        t,s=self.run_worker();self.assertEqual(t.tap.call_count,1)
        self.assertEqual(s['open_ticket_continuations'][0]['status'],'sent')
        self.assertEqual([a['kind'] for a in s['actions']],['open','ticket'])

    def test_worker_unknown_send_consumes_and_never_reopens(self):
        t,s=self.run_worker(InputDeliveryError('unknown'));self.assertEqual(t.tap.call_count,1)
        self.assertEqual(s['open_ticket_continuations'][0]['status'],'reserved')
        self.assertEqual(s['actions'][-1]['status'],'reserved')

    def test_worker_not_sent_does_not_reauthorize_the_single_confirmation(self):
        t,s=self.run_worker(TapNotSent('mouse'));self.assertEqual(t.tap.call_count,1)
        self.assertEqual(s['open_ticket_continuations'][0]['status'],'not_sent')

    def test_worker_critical_write_failure_has_no_game_input(self):
        t,s=self.run_worker(save_error=True);t.tap.assert_not_called();self.assertEqual(s,self.before)

    def test_previous_completed_claim_with_next_selection_is_not_next_episode_payment(self):
        s=self.journal.state;opened=s['actions'][0];previous='没落大地|season:2|episode:6'
        done=dict(key=previous,series='没落大地',season=2,number=6,run_id=self.old,phase='story',
                  playback_evidence='previous-play.png',completion_evidence=opened['evidence'],
                  completed_at=opened['reserved_at']-.01)
        claim=dict(id='previous-claim',kind='claim_reward',key=previous,episode=CONFIRMATION_KEY,
                   run_id=self.old,status='sent',finished_at=opened['reserved_at']-.1)
        s['completed'][previous]=done;s['actions'].insert(0,claim)
        s['actions'].insert(1,dict(claim,id='notice',kind='close_reward_notice',episode=None))
        self.journal.save();self.receipt['state_sha256']=file_sha256(self.journal.path);self.write_receipt()
        saved=copy.deepcopy(s)
        for field,value in (('kind','ticket'),('status','unknown'),('key','other'),('run_id','other')):
            original=claim[field];claim[field]=value
            self.assertIsNone(pending_source(s));claim[field]=original
        for field,value in (('playback_evidence',''),('completion_evidence','wrong.png'),('number',7),('phase','failed')):
            original=done[field];done[field]=value
            self.assertIsNone(pending_source(s));done[field]=original
        self.assertTrue(self.attach())
        for field in ('attempted','completed','actions','entry_dispatches','unresolved_entries'):
            self.assertEqual(self.journal.state[field],saved[field])
        self.assertEqual(plan(self.ticket,self.journal.state,self.run),'ticket')

    def test_private_original_context_is_recomputed_read_only_with_upstream_image_hash(self):
        from abyss_core import Observation, Token
        from theater_pending_confirmation import opening_reading
        audit=Path(__file__).resolve().parents[1]/'.local/theater-stock-20261105'
        backup=audit/'state.before-authorization.json'
        if not backup.is_file():self.skipTest('未分发第7集私有来源历史')
        state=json.loads(backup.read_text(encoding='utf-8'))
        fixture=audit/'source-fixture.json'
        if not fixture.is_file():self.skipTest('未分发私有来源位置')
        root=Path(json.loads(fixture.read_text(encoding='utf-8'))['evidence_root'])
        if not root.is_dir():self.skipTest('未分发私有来源证据')
        attempt,archive,opened=pending_source(state)
        image=root/attempt['evidence'];meta=json.loads(image.with_suffix('.json').read_text(encoding='utf-8'))
        self.assertEqual(file_sha256(image),meta['image_sha256'])
        obs=Observation(meta['width'],meta['height'],[Token(**t) for t in meta['tokens']],visuals=set(meta['visuals']))
        before=copy.deepcopy(state);raw=classify(obs);self.assertIsNone(raw.episode)
        resolved,proof=opening_reading(state,root,attempt,opened,obs,raw)
        self.assertEqual(resolved.episode.key,CONFIRMATION_KEY)
        self.assertEqual((resolved.ticket_cost,resolved.ticket_stock),(1,7))
        self.assertEqual(proof['method'],'verified_historical_reward_return')
        self.assertEqual(state,before)
        obs.visuals.discard('theater_reward_context:'+proof['claim_id'])
        failed,_=opening_reading(state,root,attempt,opened,obs,raw)
        self.assertIsNone(failed.episode)

    def test_packaging_includes_continuation_module(self):
        from build_portable import SOURCES
        self.assertIn('theater_pending_confirmation.py',SOURCES)
