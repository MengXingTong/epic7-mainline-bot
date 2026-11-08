"""Auditable old-result reconciliation + asynchronous free close regressions."""
import copy,json,tempfile,time,unittest
from dataclasses import asdict,replace
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image
from assistant_config import atomic_json,read_json
from assistant_transport import FrameSnapshot
from arena_core import Reading
from arena_journal import ArenaJournal
import arena_recovery as recovery
import test_arena_progression as progression

class ArenaRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.root=self.home/'profile';self.old='a'*32;self.new='b'*32
        self.target=dict(client='mumu',serial='127.0.0.1:16416',package='game')
        self.bind=self.target['serial'];self.image=Image.new('RGB',(1600,900))
        self.j=ArenaJournal(self.root,self.old,9);self.team=progression.team()
        from arena_core import classify
        self.team_r=classify(self.team);self.result_r=classify(progression.result())
        self.npc_r=classify(progression.npc());self.battle_r=classify(progression.battle())
        entry=self.j.evidence(FrameSnapshot(self.image,self.bind,1),self.team,self.team_r)
        for kind in ('select','challenge','entry'):
            ident=self.j.intent(kind,self.team_r,entry,self.bind);self.j.sent(ident,'sent')
        battle=self.j.evidence(FrameSnapshot(self.image,self.bind,2),progression.battle(),self.battle_r)
        self.j.battle(battle,self.bind);at=self.j.active['at'];self.key=self.j.active['key']
        self.folder=self.home/'runs'/self.old;self.folder.mkdir(parents=True)
        self.source=dict(run_id=self.old,run_dir=str(self.folder),home=str(self.home),target=self.target,
                         settings=dict(task='arena',data_dir=str(self.root),arena_count=9),requested_at=at-10)
        self.request=dict(run_id=self.new,home=str(self.home),instance_base=str(self.home),target=copy.deepcopy(self.target),
                          settings=dict(task='arena',data_dir=str(self.root),arena_count=9),requested_at=at+10)
        self.status=dict(run_id=self.old,mode='stopped',updated_at=at+5)
        atomic_json(self.folder/'request.json',self.source);atomic_json(self.folder/'status.json',self.status)
        atomic_json(self.folder/'control.json',dict(run_id=self.old,action='stop'))
        name=str(int((at+2)*1e9))+'-1234abcd'
        path=self.root/'arena/evidence'/name
        self.image.save(path.with_suffix('.png'))
        atomic_json(path.with_suffix('.json'),dict(captured_at=3,binding=self.bind,reading=asdict(Reading()),tokens=[],visuals=[]))
        self.unknown=path
        self.notice=dict(kind='status',mode='attention',attention_code='arena_unknown',wins=0,arena_requested=9,updated_at=at+2.1)
        (self.folder/'worker.log').write_text(json.dumps(self.notice)+'\n',encoding='utf-8')
    def prepare(self,reading=None):
        with patch('arena_worker.read_observation',return_value=progression.result()),patch.object(recovery,'classify',return_value=reading or self.result_r):
            return recovery.prepare(self.root,self.request,object())
    def apply(self,plan,*,reading=None,binding=None,age=0):
        snap=FrameSnapshot(self.image,binding or self.bind,time.monotonic()-age)
        return recovery.apply(plan,snap,progression.npc(),reading or self.npc_r,self.request)
    def test_real_saved_result_and_current_list_only_credit_original_run(self):
        before=read_json(self.j.path);plan=self.prepare()
        self.assertEqual(read_json(self.j.path),before)
        report=self.apply(plan);after=read_json(self.j.path)
        self.assertFalse(report['game_input_sent']);self.assertFalse(report['close_message_claimed'])
        self.assertEqual(after['runs'][self.old]['wins'],1);self.assertEqual(after['runs'][self.old]['requested'],9)
        self.assertIsNone(after['active']);self.assertIsNone(after['runs'][self.old]['pending_result'])
        self.assertEqual(after['attempted'],before['attempted']);self.assertEqual(after['entry_dispatches'],before['entry_dispatches'])
        self.assertEqual(after['actions'],before['actions']);self.assertNotIn(self.new,after['runs'])
        new=ArenaJournal(self.root,self.new,9);self.assertEqual(new.run['wins'],0);self.assertEqual(new.remaining,9)
    def test_missing_partial_or_wrong_opponent_saved_result_cannot_be_replaced_by_current_list(self):
        for reading in (Reading(),Reading('arena_battle'),Reading('arena_result',self.result_r.target,'foreign')):
            before=self.j.path.read_bytes()
            with self.assertRaises(ValueError):self.prepare(reading)
            self.assertEqual(self.j.path.read_bytes(),before)
    def test_no_battle_or_unknown_entry_send_is_not_a_win(self):
        for change in ('battle','send','active'):
            original=read_json(self.j.path);data=copy.deepcopy(original)
            if change=='battle':data['active']['battle_evidence']=None
            elif change=='active':data['active']['stock_before']=999
            else:
                data['entry_dispatches'][self.key][0]['status']='unknown'
                next(a for a in data['actions'] if a['kind']=='entry')['status']='unknown'
            atomic_json(self.j.path,data);before=self.j.path.read_bytes()
            with self.assertRaises(ValueError):self.prepare()
            self.assertEqual(self.j.path.read_bytes(),before);atomic_json(self.j.path,original)
    def test_current_list_must_be_fresh_and_bound_not_team_or_other_game(self):
        for change in ('scene','binding','age'):
            plan=self.prepare();before=self.j.path.read_bytes()
            with self.assertRaises(ValueError):
                self.apply(plan,reading=self.team_r if change=='scene' else None,binding='foreign' if change=='binding' else None,age=6 if change=='age' else 0)
            self.assertEqual(self.j.path.read_bytes(),before)
    def test_entry_image_tamper_is_detected_not_rehashed_into_permission(self):
        path=self.root/'arena'/self.j.active['entry_evidence']['image'];path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'哈希'):self.prepare()
    def test_changed_request_journal_or_source_log_invalidates_plan(self):
        for change in ('request','journal','log'):
            plan=self.prepare();original=self.j.path.read_bytes();log=(self.folder/'worker.log').read_bytes()
            if change=='request':self.request['settings']['arena_count']=8
            elif change=='journal':self.j.path.write_bytes(original+b' ')
            else:(self.folder/'worker.log').write_bytes(log+b' ')
            before=self.j.path.read_bytes()
            with self.assertRaises(ValueError):self.apply(plan)
            self.assertEqual(self.j.path.read_bytes(),before)
            self.j.path.write_bytes(original);(self.folder/'worker.log').write_bytes(log);self.request['settings']['arena_count']=9
    def test_original_target_stop_or_unknown_attention_link_cannot_be_guessed(self):
        for change in ('target','stop','notice'):
            original=copy.deepcopy(self.request);control=(self.folder/'control.json').read_bytes();log=(self.folder/'worker.log').read_bytes()
            if change=='target':self.request['target']['serial']='127.0.0.1:16384'
            elif change=='stop':atomic_json(self.folder/'control.json',dict(run_id=self.old,action='run'))
            else:(self.folder/'worker.log').write_text('',encoding='utf-8')
            before=self.j.path.read_bytes()
            with self.assertRaises(ValueError):self.prepare()
            self.assertEqual(self.j.path.read_bytes(),before)
            self.request=original;(self.folder/'control.json').write_bytes(control);(self.folder/'worker.log').write_bytes(log)
    def test_positive_defeat_before_later_victory_never_restores_a_retry(self):
        fail=dict(kind='status',attention_code='arena_defeat',updated_at=self.j.active['at']+1)
        (self.folder/'worker.log').write_text(json.dumps(fail)+'\n'+json.dumps(self.notice)+'\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'战败'):self.prepare()
    def test_evidence_or_intent_write_failure_does_not_release_entry(self):
        for where in ('evidence','intent'):
            plan=self.prepare();before=self.j.path.read_bytes()
            manager=patch.object(recovery,'atomic_json',side_effect=OSError('disk full')) if where=='evidence' else patch.object(plan['journal'],'save',side_effect=OSError('disk full'))
            with manager:
                with self.assertRaises(OSError):self.apply(plan)
            self.assertEqual(self.j.path.read_bytes(),before)
    def test_interrupted_reconciliation_resumes_facts_once_not_another_win(self):
        plan=self.prepare()
        with patch.object(plan['journal'],'acknowledge_reconciled_return',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):self.apply(plan)
        after=read_json(self.j.path);self.assertEqual(after['runs'][self.old]['wins'],1)
        with self.assertRaises(ValueError):ArenaJournal(self.root,self.new,9)
        again=self.prepare();self.apply(again);after=read_json(self.j.path)
        self.assertEqual(after['runs'][self.old]['wins'],1);self.assertIsNone(after['runs'][self.old]['pending_result'])
    def test_failed_close_restarts_original_quota_not_fresh_nine(self):
        evidence=self.j.evidence(FrameSnapshot(self.image,self.bind,3),progression.result(),self.result_r)
        self.j.complete(evidence,self.bind)
        self.status.update(mode='blocked',scene='arena_result',wins=1)
        atomic_json(self.folder/'status.json',self.status);atomic_json(self.folder/'control.json',dict(run_id=self.old,action='run'))
        with patch('arena_worker.read_observation',side_effect=[progression.result(),progression.npc()]),patch.object(recovery,'classify',side_effect=[self.result_r,self.npc_r]):
            resumed=recovery.reconcile(self.root,self.request,object(),lambda:FrameSnapshot(self.image,self.bind,time.monotonic()),Mock())
        self.assertEqual(resumed,self.old)
        j=ArenaJournal(self.root,resumed,9);self.assertEqual(j.remaining,8);self.assertNotIn(self.new,j.state['runs'])
    def test_failure_closing_last_win_finishes_original_quota_without_starting_another_batch(self):
        self.j.run['requested']=1;self.j.save()
        self.source['settings']['arena_count']=1;atomic_json(self.folder/'request.json',self.source)
        self.request['settings']['arena_count']=1
        evidence=self.j.evidence(FrameSnapshot(self.image,self.bind,3),progression.result(),self.result_r)
        self.j.complete(evidence,self.bind)
        self.status.update(mode='blocked',scene='arena_result',wins=1)
        atomic_json(self.folder/'status.json',self.status);atomic_json(self.folder/'control.json',dict(run_id=self.old,action='run'))
        with patch('arena_worker.read_observation',side_effect=[progression.result(),progression.npc()]),patch.object(recovery,'classify',side_effect=[self.result_r,self.npc_r]):
            resumed=recovery.reconcile(self.root,self.request,object(),lambda:FrameSnapshot(self.image,self.bind,time.monotonic()),Mock())
        self.assertEqual(resumed,self.old);j=ArenaJournal(self.root,resumed,1)
        self.assertEqual(j.remaining,0);self.assertNotIn(self.new,j.state['runs'])

    def test_replay_plan_cannot_be_consumed_twice(self):
        plan=self.prepare();self.apply(plan)
        with self.assertRaises(ValueError):self.apply(plan)

class ResultCloseResponseTests(unittest.TestCase):
    def test_ocr_position_jitter_does_not_change_control_identity(self):
        import arena_worker
        a=Reading('arena_result',progression.token('确认',.915,.92),'NPC A')
        b=Reading('arena_result',progression.token('确认',.916,.921),'NPC A')
        self.assertEqual(arena_worker.signature(a),arena_worker.signature(b))
    def test_same_result_remains_for_several_frames_then_disappears_without_duplicate_error(self):
        rows=[progression.npc(),progression.npc(True),progression.team(),progression.battle(),progression.result()]
        for shift in (0.1,0.4,0.8):
            o=progression.result();o.tokens[2]=replace(o.tokens[2],x=o.tokens[2].x+shift);rows.append(o)
        rows.append(progression.npc())
        tr,control,state,_=progression.ArenaProgressionTests.exercise(self,rows)
        self.assertEqual(len([v for v in tr.inputs if v[1]=='result_close']),1)
        self.assertFalse(control.attentions);self.assertEqual(state['runs']['current-frame']['wins'],1)
        self.assertIsNone(state['runs']['current-frame']['pending_result'])
    def test_free_close_responses_are_fresh_bounded_and_preserve_original_sends(self):
        from arena_core import classify
        with tempfile.TemporaryDirectory() as root:
            j=ArenaJournal(root,'one',1);r=classify(progression.team());ev=dict(captured_at=1)
            for kind in ('select','challenge','entry'):
                ident=j.intent(kind,r,ev,'w');j.sent(ident,'sent')
            j.battle(dict(captured_at=2),'w');j.complete(dict(captured_at=3),'w')
            r=classify(progression.result())
            for i in range(3):
                with patch('arena_journal.time.time',return_value=10+i*3):
                    ident=j.intent('result_close',r,dict(captured_at=4+i),'w');j.sent(ident,'sent')
                    self.assertFalse(j.result_close_ready(4+i+.5))
            original=copy.deepcopy(j.state['actions'])
            last=j.state['actions'][-1];saved_status=last['status'];last['status']='unknown'
            with patch('arena_journal.time.time',return_value=30):self.assertFalse(j.result_close_ready(10))
            last['status']=saved_status
            with patch('arena_journal.time.time',return_value=30):
                self.assertFalse(j.result_close_ready(10))
                with self.assertRaises(ValueError):j.intent('result_close',r,dict(captured_at=10),'w')
            self.assertEqual(j.state['actions'],original);self.assertEqual(len(j.state['attempted']),1)
            j.acknowledge_close(dict(captured_at=11),'w');self.assertIsNone(j.run['pending_result'])

if __name__=='__main__':unittest.main()
