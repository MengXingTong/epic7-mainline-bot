"""A durable intent must survive expensive persistence without aging its target."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import runner
from entry_preparation import dispatch_first_entry,EntryPreparationDeferred
from test_story_only_nodes import fake_runner,frame
from pc_backend import TapNotSent

class EntryPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'evidence').mkdir()
        self.r=fake_runner(frame());self.r.run_id='original-run';self.r.pc=None
        self.r.cfg.update(serial='known',package='game')
        self.r.action=runner.Runner.action.__get__(self.r,runner.Runner)
        self.r.ensure_game=Mock();self.r.adb=Mock()
        self.r.evidence=runner.Runner.evidence.__get__(self.r,runner.Runner)
        self.timeline=[]
        self.r.save.side_effect=lambda:self.timeline.append('save')
        self.r.adb.side_effect=lambda *a:self.timeline.append('send')
        self.r.capture=Mock(side_effect=self.fresh)
        self.root_patch=patch.object(runner,'ROOT',self.root);self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.event_patch=patch.object(runner,'event');self.event_patch.start();self.addCleanup(self.event_patch.stop)
    def fresh(self):
        self.timeline.append('capture');self.r.frame=copy.deepcopy(frame());self.r.frame.at=time.time();return self.r.frame
    def open(self):
        d=self.r.map_ticket(self.r.frame)[0]
        self.r.ticket=dict(d,evidence=self.r.evidence('preflight'))
        return self.r.open_story_node(d,runner.mainline_map_control(self.r.frame)['target'])
    def dispatch(self):
        return self.r.s['entry_dispatches']['E4-C4-S3'][0]
    def receipt(self):
        return self.root/'evidence'/('entry-invocation-'+self.dispatch()['id']+'.json')
    def test_current_observation_used_once_after_durable_entry_intent(self):
        self.assertTrue(self.open()[0]);self.assertEqual(self.r.adb.call_count,1)
        send=self.timeline.index('send');self.assertIn('save',self.timeline[:send]);self.r.capture.assert_not_called()
        self.assertEqual(self.dispatch()['status'],'sent')
        self.assertEqual(json.loads(self.receipt().read_text(encoding='utf8'))['status'],'sent')
        self.assertEqual(len(self.r.s['entry_dispatches']['E4-C4-S3']),1)
    def test_legacy_dispatch_without_preparation_id_is_observation_only(self):
        from entry_preparation import continue_prepared_entry
        for status in ('reserved','unknown','sent','not_sent'):
            for fields in ({},{'id':None},{'id':''},{'id':0}):
                with self.subTest(status=status,fields=fields):
                    self.r.s.update(active={'key':'legacy'},attempted={'legacy':{'cost':8}},
                                    entry_dispatches={'legacy':[dict(status=status,**fields)]})
                    original=copy.deepcopy(self.r.s)
                    self.assertIsNone(continue_prepared_entry(self.r,'map'))
                    self.assertEqual(self.r.s,original);self.r.adb.assert_not_called()
                    self.r.save.assert_not_called()
    def test_expensive_save_defers_expired_observation_without_extra_capture_or_send(self):
        clock=[time.time()]
        def save():self.timeline.append('save');clock[0]+=20
        def fresh():
            self.timeline.append('capture');self.r.frame=copy.deepcopy(frame());self.r.frame.at=clock[0];return self.r.frame
        self.r.save.side_effect=save;self.r.capture.side_effect=fresh
        with patch('time.time',side_effect=lambda:clock[0]):
            with self.assertRaises(EntryPreparationDeferred):self.open()
        self.r.adb.assert_not_called();self.r.capture.assert_not_called();self.assertEqual(self.dispatch()['status'],'reserved')
    def test_unknown_or_expired_final_frame_keeps_prepared_without_any_invocation(self):
        def stale():self.fresh();self.r.frame.at-=6;return self.r.frame
        self.r.frame.at-=6
        with self.assertRaises(EntryPreparationDeferred):self.open()
        self.r.adb.assert_not_called();self.assertFalse(self.receipt().exists());self.assertEqual(self.dispatch()['status'],'reserved')
        original=copy.deepcopy(self.r.s['attempted'])
        self.r.capture.side_effect=self.fresh;self.r.frame=frame()
        keep,_=self.r.step(self.r.frame)
        self.assertTrue(keep);self.r.adb.assert_called_once()
        self.assertEqual(self.r.s['attempted'],original);self.assertEqual(self.dispatch()['status'],'sent')
    def test_unknown_send_is_consumed_not_reusable_or_called_not_sent(self):
        self.r.adb.side_effect=RuntimeError('发送结果不明')
        with self.assertRaises(RuntimeError):self.open()
        preparation=self.r.s['entry_preparations'][self.dispatch()['id']]
        self.assertEqual(preparation['phase'],'unknown');self.assertEqual(self.dispatch()['status'],'reserved')
        self.assertEqual(json.loads(self.receipt().read_text(encoding='utf8'))['status'],'unknown')
        with self.assertRaises(ValueError):dispatch_first_entry(self.r,self.dispatch(),'观看故事（仅一次）',resume=True)
        self.r.adb.assert_called_once()
    def test_critical_invocation_write_failure_does_not_call_the_backend(self):
        with patch('runner.atomic_json',side_effect=OSError('关键记录失败')):
            with self.assertRaises(OSError):self.open()
        self.r.adb.assert_not_called();self.assertEqual(self.dispatch()['status'],'reserved')
    def test_target_change_never_uses_the_original_coordinates(self):
        def changed():
            f=self.fresh();f.words[2]['text']='4. 别的节点';return f
        self.r.save.side_effect=lambda:changed()
        with self.assertRaises(EntryPreparationDeferred):self.open()
        self.r.adb.assert_not_called();self.assertFalse(self.receipt().exists())
    def test_uninvoked_plan_cannot_block_known_story_or_claim_external_battle(self):
        from entry_preparation import continue_prepared_entry
        def stale():self.fresh();self.r.frame.at-=6;return self.r.frame
        self.r.frame.at-=6
        with self.assertRaises(EntryPreparationDeferred):self.open()
        original=copy.deepcopy(self.r.s['active']);attempts=copy.deepcopy(self.r.s['attempted'])
        self.r.frame=frame();self.r.frame.at=time.time()
        self.assertIsNone(continue_prepared_entry(self.r,'story'))
        self.assertIsNone(self.r.s['active']);self.assertEqual(self.r.s['unresolved_entries'][-1]['entry'],original)
        self.assertEqual(self.r.s['attempted'],attempts);self.assertEqual(self.dispatch()['status'],'reserved')
        self.assertEqual(self.r.s['completed'],{});self.r.adb.assert_not_called()
        self.assertEqual(self.r.s['entry_preparations'][self.dispatch()['id']]['phase'],'external_progress')
    def test_invoked_receipt_never_uses_the_external_progress_path(self):
        from entry_preparation import continue_prepared_entry
        def stale():self.fresh();self.r.frame.at-=6;return self.r.frame
        self.r.frame.at-=6
        with self.assertRaises(EntryPreparationDeferred):self.open()
        self.receipt().write_text('{"status":"invoking"}',encoding='utf8')
        with self.assertRaises(ValueError):continue_prepared_entry(self.r,'story')
        self.assertIsNotNone(self.r.s['active']);self.r.adb.assert_not_called()

    def test_a_reserved_plan_is_not_observed_game_acceptance(self):
        from story_open_ack import StoryOpenAcknowledgement
        def stale():self.fresh();self.r.frame.at-=6;return self.r.frame
        self.r.frame.at-=6
        with self.assertRaises(EntryPreparationDeferred):self.open()
        acknowledgement=StoryOpenAcknowledgement(self.r)
        acknowledgement.observe_scene('story',self.r.frame)
        self.assertEqual(self.r.s['story_open_acknowledgements'][self.dispatch()['id']]['phase'],'awaiting_acceptance')
        self.r.adb.assert_not_called()

    def test_received_invocation_receipt_blocks_another_dispatch(self):
        self.open();self.dispatch()['status']='reserved'
        prep=self.r.s['entry_preparations'][self.dispatch()['id']];prep['phase']='prepared'
        with self.assertRaises(ValueError):dispatch_first_entry(self.r,self.dispatch(),'观看故事（仅一次）',resume=True)
        self.r.adb.assert_called_once()

    def test_expiry_in_read_only_game_guard_does_not_consume_input(self):
        clock=[time.time()]
        self.r.frame.at=clock[0]
        self.r.ensure_game.side_effect=lambda:clock.__setitem__(0,clock[0]+6)
        with patch('time.time',side_effect=lambda:clock[0]):
            with self.assertRaises(EntryPreparationDeferred):self.open()
        self.r.adb.assert_not_called();self.assertFalse(self.receipt().exists())
        self.assertEqual(self.r.s['entry_preparations'][self.dispatch()['id']]['phase'],'prepared')
        self.assertEqual(self.dispatch()['status'],'reserved')
        original=copy.deepcopy(self.r.s['attempted'])
        self.r.ensure_game.side_effect=None;self.r.frame=frame()
        self.assertTrue(self.r.step(self.r.frame)[0]);self.r.adb.assert_called_once()
        self.assertEqual(self.r.s['attempted'],original);self.assertEqual(self.dispatch()['status'],'sent')

    def test_expiry_in_actual_input_backend_stays_unknown(self):
        from pc_backend import FrameExpired
        self.r.adb.side_effect=FrameExpired('backend expired')
        with self.assertRaises(FrameExpired):self.open()
        self.assertEqual(self.r.s['entry_preparations'][self.dispatch()['id']]['phase'],'unknown')
        self.assertEqual(json.loads(self.receipt().read_text(encoding='utf8'))['input_boundary'],'called')
        self.r.adb.assert_called_once()
        with self.assertRaises(ValueError):dispatch_first_entry(self.r,self.dispatch(),'观看故事（仅一次）',resume=True)

    def test_expiry_during_tiny_receipt_write_retires_intent_and_next_cycle_uses_new_receipt(self):
        clock=[time.time()];self.r.frame.at=clock[0];write=runner.atomic_json
        def slow(path,value,**kw):
            write(path,value,**kw)
            if value.get('status')=='invoking':clock[0]+=6
        with patch('time.time',side_effect=lambda:clock[0]),patch('runner.atomic_json',side_effect=slow):
            with self.assertRaises(EntryPreparationDeferred):self.open()
        old=self.receipt().read_bytes();self.r.adb.assert_not_called()
        self.assertEqual(json.loads(old)['status'],'cancelled_before_backend')
        prep=self.r.s['entry_preparations'][self.dispatch()['id']]
        self.assertEqual(prep['phase'],'prepared');self.assertEqual(len(prep['guard_cancellations']),1)
        self.r.frame=frame();self.r.step(self.r.frame);self.r.adb.assert_called_once()
        self.assertEqual(self.receipt().read_bytes(),old)
        new=self.receipt().with_name('entry-invocation-'+self.dispatch()['id']+'-1.json')
        self.assertEqual(json.loads(new.read_text(encoding='utf8'))['status'],'sent')
        self.assertEqual(len(self.r.s['entry_dispatches'][self.dispatch()['entry']['key']]),1)

    def test_tampered_cancelled_receipt_does_not_release_another_input(self):
        clock=[time.time()];self.r.frame.at=clock[0];write=runner.atomic_json
        def slow(path,value,**kw):
            write(path,value,**kw)
            if value.get('status')=='invoking':clock[0]+=6
        with patch('time.time',side_effect=lambda:clock[0]),patch('runner.atomic_json',side_effect=slow):
            with self.assertRaises(EntryPreparationDeferred):self.open()
        self.receipt().write_text('{}',encoding='utf8');self.r.frame=frame()
        with self.assertRaises(ValueError):self.r.step(self.r.frame)
        self.r.adb.assert_not_called()

    def test_safety_change_and_critical_write_errors_still_raise(self):
        from pc_backend import PcSafetyError
        self.r.ensure_game.side_effect=PcSafetyError('geometry changed')
        with self.assertRaises(PcSafetyError):self.open()
        self.r.adb.assert_not_called();self.assertFalse(self.receipt().exists())
        self.assertEqual(self.r.s['entry_preparations'][self.dispatch()['id']]['phase'],'prepared')


if __name__=='__main__':unittest.main()
