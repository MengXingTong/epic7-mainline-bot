"""Legacy pre-input cancellations require explicit hash-bound maintenance only."""
import copy,datetime,hashlib,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import runner
from entry_journal import reserve_entry
from entry_preparation import digest,register_guard_continuation,continue_guard_continuation,continue_prepared_entry
from pc_backend import InputDeliveryError
from test_story_only_nodes import frame,fake_runner
from test_team_preparation import preparation

SOURCE="""class Runner:
    def _action(self,kind,word=None,xy=None):
        self.ensure_game()
        if time.time()-self.frame.at>5:
            from pc_backend import FrameExpired
            raise FrameExpired('观察画面已过期；已取消操作。')
        self.adb('shell','input','tap',1,2)
"""

class GuardContinuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'evidence').mkdir();(self.root/'.local').mkdir()
        self.root_patch=patch.object(runner,'ROOT',self.root);self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.code_patch=patch.object(runner,'CODE_ROOT',self.root);self.code_patch.start();self.addCleanup(self.code_patch.stop)
        self.event_patch=patch.object(runner,'event');self.event_patch.start();self.addCleanup(self.event_patch.stop)
        self.r=fake_runner(frame('准备战斗'));self.r.run_id='new-current-run';self.r.pc=None
        self.r.cfg.update(serial='known',package='game')
        d=self.r.map_ticket(self.r.frame)[0];self.key=d['key']
        self.original=dict(d,cost=20,stamina_before=100,team_entry_mode='single_task',phase='support',
                           start_epoch=time.time()-100,started_at='original')
        dispatch=reserve_entry(self.r.s,self.key,self.original);self.did=dispatch['id']
        old=dict(id=self.did,key=self.key,action='进行任务（仅一次入场）',phase='unknown',run_id='old-run',
                 original_sha256=dispatch['original_sha256'],binding=dict(client='mumu',serial='known',package='game'),
                 raw_size=[1600,900],reason='观察画面已过期；已取消操作。',
                 invocation=str(Path('evidence')/('entry-invocation-'+self.did+'.json')))
        self.r.s['entry_preparations']={self.did:old}
        self.r.s['unresolved_entries']=[dict(reason='new current-screen run',entry=copy.deepcopy(self.original))]
        self.r.s['entry_acceptances']={}
        self.receipt=self.root/old['invocation'];now=time.time()-90
        value=dict(id=self.did,key=self.key,action=old['action'],run_id=old['run_id'],status='unknown',reason=old['reason'],
                   binding=old['binding'],original_sha256=old['original_sha256'],captured_at=now,reserved_at=now+4.6,finished_at=now+5.2)
        self.receipt.write_text(json.dumps(value,ensure_ascii=False),encoding='utf8')
        self.events=self.root/'events.jsonl';self.events.write_text('',encoding='utf8')
        self.source=self.root/'.local/old-runner.py';self.source.write_text(SOURCE,encoding='utf8')
        self.seed=dict(run_id=self.r.run_id,key=self.key,dispatch_id=self.did,state_sha256='source-state',
                       events_sha256=self.sha(self.events),preparation_sha256=digest(old),receipt_sha256=self.sha(self.receipt),
                       archive_sha256=digest(self.r.s['unresolved_entries'][0]),source_runner=str(self.source),source_runner_sha256=self.sha(self.source))
        self.proof=dict(nonce='explicit-new-continuation',state_sha256='source-state',source_events_sha256=self.seed['events_sha256'],
                        user_authorization='Fix the reviewed pre-input cancellation and continue the first actual entry')
        self.r.action=runner.Runner.action.__get__(self.r,runner.Runner)
        self.r.ensure_game=Mock();self.r.adb=Mock();self.r.evidence=runner.Runner.evidence.__get__(self.r,runner.Runner)
        self.r.capture=Mock();self.r.back=Mock();self.protected=copy.deepcopy(self.r.s)
    @staticmethod
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    def register(self):register_guard_continuation(self.r,self.seed,self.proof)
    def team(self):
        f=preparation();f.find('新关卡')['text']=self.original['name'];self.r.frame=f;return f
    def map(self):
        self.r.frame=frame('准备战斗')
        d,rows,proof=runner.Runner.map_ticket(self.r,self.r.frame)
        rows[-1]['locked']=True
        self.r.map_ticket=Mock(return_value=(d,rows,proof))
        return self.r.frame
    def unchanged(self):
        for k in ('attempted','completed','entry_preparations','unresolved_entries'):
            self.assertEqual(self.r.s[k],self.protected[k])
        self.assertEqual(self.sha(self.receipt),self.seed['receipt_sha256'])
    def test_registration_alone_never_sends_or_adopts_archive(self):
        self.register();self.r.adb.assert_not_called();self.assertIsNone(self.r.s['active']);self.unchanged()
        with self.assertRaises(ValueError):self.register()
    def test_no_seed_means_old_unknown_and_archive_remain_blocked(self):
        self.assertIsNone(continue_prepared_entry(self.r,'map'));self.r.adb.assert_not_called()
        self.assertIsNone(self.r.s['active']);self.unchanged()
    def test_map_then_team_sends_first_actual_entry_once_with_separate_receipt(self):
        self.register();self.map();self.assertTrue(continue_prepared_entry(self.r,'map')[0])
        self.assertIsNone(self.r.s['active']);self.team();self.assertTrue(continue_prepared_entry(self.r,'team')[0])
        self.assertEqual(self.r.adb.call_count,2);self.unchanged()
        self.assertEqual(len(self.r.s['entry_dispatches'][self.key]),1)
        self.assertEqual(self.r.s['entry_dispatches'][self.key][0]['status'],'sent')
        c=self.r.s['entry_preparation_continuations'][self.did]
        self.assertEqual(c['phase'],'submitted');self.assertEqual(c['plan']['phase'],'sent')
        value=json.loads((self.root/c['plan']['invocation']).read_text(encoding='utf8'))
        self.assertEqual(value['status'],'sent');self.assertIsNone(continue_prepared_entry(self.r,'team'))
        self.assertEqual(self.r.adb.call_count,2);self.r.capture.assert_not_called()
    def test_team_without_fresh_map_returns_instead_of_entering(self):
        self.register();self.team();continue_prepared_entry(self.r,'team')
        self.r.back.assert_called_once();self.r.adb.assert_not_called();self.assertIsNone(self.r.s['active'])
        continue_prepared_entry(self.r,'team');self.r.back.assert_called_once()
    def test_stale_map_never_directly_opens_resource_entry(self):
        self.register();self.map();continue_prepared_entry(self.r,'map')
        self.r.s['entry_preparation_continuations'][self.did]['map_ticket']['verified_epoch']-=121
        self.team();continue_prepared_entry(self.r,'team');self.r.back.assert_called_once()
        self.assertIsNone(self.r.s['active']);self.assertEqual(self.r.adb.call_count,1)
    def test_unknown_input_consumes_continuation_and_never_repeats(self):
        self.register();self.map();continue_prepared_entry(self.r,'map');self.team()
        self.r.adb.side_effect=InputDeliveryError('unknown')
        with self.assertRaises(InputDeliveryError):continue_prepared_entry(self.r,'team')
        before=self.r.adb.call_count;self.assertIsNone(continue_prepared_entry(self.r,'team'))
        self.assertEqual(self.r.adb.call_count,before);self.unchanged()
    def test_current_map_must_prove_same_uncleared_node_and_locked_successor(self):
        self.register();self.map();d,rows,proof=self.r.map_ticket(self.r.frame)
        for change in ('key','locked','clear','next','control'):
            with self.subTest(change=change):
                node=copy.deepcopy(d);maprows=copy.deepcopy(rows)
                if change=='key':node['key']='other'
                if change=='locked':node['locked']=True
                if change=='clear':node['clear_badge']=True
                if change=='next':maprows[-1]['locked']=False
                self.r.map_ticket=Mock(return_value=(node,maprows,proof))
                with patch('runner.mainline_map_control',return_value=None) if change=='control' else patch('runner.event'):
                    continue_prepared_entry(self.r,'map')
                self.r.adb.assert_not_called()
    def test_known_free_notice_is_not_blocked_by_map_recheck(self):
        self.register();self.assertIsNone(continue_guard_continuation(self.r,'tutorial_completed_notice'))
        self.r.adb.assert_not_called();self.assertIsNone(self.r.s['active'])
    def test_external_real_progress_revokes_uninvoked_continuation(self):
        self.register();self.assertIsNone(continue_guard_continuation(self.r,'battle'))
        self.assertEqual(self.r.s['entry_preparation_continuations'][self.did]['phase'],'external_progress')
        self.map();self.assertIsNone(continue_guard_continuation(self.r,'map'));self.r.adb.assert_not_called()
    def test_source_acceptance_or_extra_input_never_registers(self):
        for change in ('authorization','state','events','receipt','archive','accepted','sent','completed','active','code','binding'):
            with self.subTest(change=change):
                state=copy.deepcopy(self.r.s);seed=copy.deepcopy(self.seed);proof=copy.deepcopy(self.proof)
                if change=='authorization':proof['user_authorization']=''
                elif change=='state':seed['state_sha256']='other'
                elif change=='events':seed['events_sha256']='other'
                elif change=='receipt':seed['receipt_sha256']='other'
                elif change=='archive':seed['archive_sha256']='other'
                elif change=='accepted':self.r.s['entry_acceptances'][self.did]={'mode':'battle'}
                elif change=='sent':self.r.s['entry_dispatches'][self.key][0]['status']='sent'
                elif change=='completed':self.r.s['completed'][self.key]={}
                elif change=='active':self.r.s['active']=copy.deepcopy(self.original)
                elif change=='code':seed['source_runner_sha256']='other'
                elif change=='binding':self.r.cfg['serial']='other'
                with self.assertRaises(ValueError):register_guard_continuation(self.r,seed,proof)
                self.r.s=state;self.r.cfg['serial']='known';self.r.adb.assert_not_called()
    def test_post_cancel_action_rejects_even_if_hash_is_explicit(self):
        now=datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.events.write_text(json.dumps(dict(time=now,kind='action',action='any input'))+'\n',encoding='utf8')
        self.seed['events_sha256']=self.sha(self.events);self.proof['source_events_sha256']=self.sha(self.events)
        with self.assertRaises(ValueError):self.register()
        self.r.adb.assert_not_called()
    def test_source_raise_after_input_is_not_the_reviewed_guard(self):
        self.source.write_text(SOURCE.replace('        self.ensure_game()','        self.adb("shell","input","tap",1,2)'),encoding='utf8')
        self.seed['source_runner_sha256']=self.sha(self.source)
        with self.assertRaises(ValueError):self.register()
        self.r.adb.assert_not_called()

if __name__=='__main__':unittest.main()
