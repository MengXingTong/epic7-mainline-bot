"""Selection acceptance, OCR drift and interrupted-quota regressions (synthetic)."""
import copy,json,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock,patch
from PIL import Image,ImageDraw
from assistant_config import atomic_json,read_json
from assistant_transport import FrameSnapshot
from arena_core import Reading,classify
from arena_journal import ArenaJournal
from arena_vision import apply as vision
import arena_recovery as recovery
import test_arena_progression as p


class ArenaSelectionTests(unittest.TestCase):
    def exercise(self,*args,**kwargs):return p.ArenaProgressionTests.exercise(self,*args,**kwargs)

    def test_retiring_row_replaced_by_different_opponent_is_reselected_before_challenge(self):
        rows=[p.npc(name='old'),p.npc(name='old'),p.npc(True,name='new'),p.npc(True,name='new'),p.team(name='new')]
        tr,c,s,_=self.exercise(rows)
        self.assertEqual([(i,k) for i,k,_ in tr.inputs],[(1,'select'),(3,'select'),(4,'challenge'),(5,'entry')])
        self.assertFalse(c.attentions)
        self.assertEqual(s['active']['opponent'],'new')
        self.assertEqual([a['reading']['opponent'] for a in s['actions'] if a['kind']=='select'],['old','new'])

    def test_challenge_text_without_selection_and_enabled_pixels_does_not_authorize(self):
        for missing in ('arena_npc_first_selected','arena_challenge_enabled'):
            o=p.npc(True);o.visuals.remove(missing)
            tr,c,s,_=self.exercise([p.npc(),o,o])
            self.assertEqual([k for _,k,_ in tr.inputs],['select'])
            self.assertFalse(s['attempted']);self.assertFalse(c.attentions)

    def test_ocr_name_drift_after_challenge_cannot_resend_challenge(self):
        rows=[p.npc(name='女仆主国特别公演'),p.npc(True,name='女仆主国特别公演'),
              p.npc(True,name='女仆王国特别公演'),p.npc(True,name='女仆王国特别公演')]
        tr,c,s,_=self.exercise(rows)
        self.assertEqual([k for _,k,_ in tr.inputs],['select','challenge'])
        self.assertFalse(s['attempted']);self.assertFalse(c.attentions)

    def test_wrong_team_returns_once_then_reselects_without_spending_for_wrong_team(self):
        wrong=p.team(name='new');wrong.visuals.add('arena_native_back')
        rows=[p.npc(name='old'),p.npc(True,name='old'),wrong,wrong,p.npc(True,name='new'),p.npc(True,name='new'),p.team(name='new')]
        tr,c,s,_=self.exercise(rows)
        self.assertEqual([(i,k) for i,k,_ in tr.inputs],[(1,'select'),(2,'challenge'),(3,'return_to_npc'),(5,'select'),(6,'challenge'),(7,'entry')])
        self.assertFalse(c.attentions);self.assertEqual(len(s['attempted']),1)
        self.assertEqual(next(iter(s['attempted'].values()))['opponent'],'new')
        self.assertEqual(next(a for a in s['actions'] if a['kind']=='return_to_npc')['input'],'native_back')

    def test_unknown_modal_missing_arrow_foreign_team_and_resource_still_zero_input(self):
        for mode in ('modal','arrow','resource'):
            o=p.team(name='new')
            if mode!='arrow':o.visuals.add('arena_native_back')
            if mode=='modal':o.tokens.append(p.token('确认',.5,.5))
            if mode=='resource':o.tokens.append(p.token('购买挑战书',.5,.5))
            rows=[p.npc(name='old'),p.npc(True,name='old'),o]
            tr,c,s,_=self.exercise(rows)
            self.assertFalse(any(k in ('entry','return_to_npc') for _,k,_ in tr.inputs));self.assertFalse(s['attempted'])

    def test_paid_entry_already_sent_never_returns_or_reenters_for_changed_team(self):
        wrong=p.team(name='new');wrong.visuals.add('arena_native_back')
        tr,c,s,_=self.exercise([p.npc(),p.npc(True),p.team(),wrong])
        self.assertEqual([k for _,k,_ in tr.inputs],['select','challenge','entry'])
        self.assertEqual(len(s['attempted']),1)

    def test_navigation_send_error_or_evidence_write_failure_never_returns_again(self):
        o=p.team(name='new');o.visuals.add('arena_native_back')
        for fail in ('return_to_npc','unknown_return_to_npc'):
            tr,c,s,_=self.exercise([p.npc(),p.npc(True),o,o],fail_on=fail,
                expect_error=RuntimeError if fail.startswith('unknown') else None)
            self.assertEqual(sum(k=='return_to_npc' for _,k,_ in tr.inputs),1)
            self.assertEqual(s['actions'][-1]['status'],'unknown' if fail.startswith('unknown') else 'not_sent')
            self.assertFalse(s['attempted'])

    def test_return_intent_write_failure_sends_no_back_and_preserves_original_sends(self):
        o=p.team(name='new');o.visuals.add('arena_native_back')
        original=ArenaJournal.intent
        def reserve(j,kind,*args):
            if kind=='return_to_npc':raise OSError('cannot persist return intent')
            return original(j,kind,*args)
        tr,c,s,_=self.exercise([p.npc(),p.npc(True),o],patches=[patch.object(ArenaJournal,'intent',reserve)],expect_error=OSError)
        self.assertEqual([k for _,k,_ in tr.inputs],['select','challenge'])
        self.assertTrue(all(a['status']=='sent' for a in s['actions']));self.assertFalse(s['attempted'])

    def test_journal_rejects_different_challenge_and_team_names(self):
        with tempfile.TemporaryDirectory() as root:
            j=ArenaJournal(root,'r',9);ev=dict(captured_at=1);a=classify(p.team(name='A'));b=classify(p.team(name='B'))
            i=j.intent('select',a,ev,'w');j.sent(i,'sent')
            with self.assertRaises(ValueError):j.intent('challenge',b,ev,'w')
            i=j.intent('challenge',a,ev,'w');j.sent(i,'sent')
            before=copy.deepcopy(j.state)
            with self.assertRaises(ValueError):j.intent('entry',b,ev,'w')
            with self.assertRaises(ValueError):j.intent('challenge',a,ev,'w')
            self.assertEqual(before,j.state)

    def test_challenge_before_latest_select_does_not_authorize_entry(self):
        with tempfile.TemporaryDirectory() as root:
            j=ArenaJournal(root,'r',9);r=classify(p.team());ev=dict(captured_at=1)
            for kind in ('select','challenge','select'):
                i=j.intent(kind,r,ev,'w');j.sent(i,'sent')
            self.assertFalse(j.entry_chain_matches(r,'w'))
            with self.assertRaises(ValueError):j.intent('entry',r,ev,'w')

    def test_native_acceptance_pixels_and_back_arrow_are_independent(self):
        for selected,enabled,back in ((False,False,False),(True,False,False),(False,True,False),(True,True,True)):
            image=Image.new('RGB',(1600,900),(35,35,35));d=ImageDraw.Draw(image)
            if selected:d.rectangle((480,324,1200,344),fill=(210,185,60))
            if enabled:
                d.rectangle((672,801,928,855),fill=(30,85,40));d.rectangle((775,815,825,830),fill='white')
            if back:d.line([(61,20),(34,40),(61,61)],fill='white',width=8)
            o=vision(image,p.npc())
            self.assertEqual('arena_npc_first_selected' in o.visuals,selected)
            self.assertEqual('arena_challenge_enabled' in o.visuals,enabled)
            self.assertEqual('arena_native_back' in o.visuals,back)


class ArenaNavigationQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name);self.root=self.home/'profile';self.old='a'*32;self.new='b'*32
        self.target=dict(client='mumu',serial='127.0.0.1:16416',package='game');self.bind=self.target['serial']
        self.image=Image.new('RGB',(1600,900));self.j=ArenaJournal(self.root,self.old,9);self.started=time.time()-10
        at=0
        def evidence(o):
            nonlocal at
            at+=1;return self.j.evidence(FrameSnapshot(self.image,self.bind,at),o,classify(o))
        for index in range(4):
            for kind,o in [('select',p.npc()),('challenge',p.npc(True)),('entry',p.team())]:
                i=self.j.intent(kind,classify(o),evidence(o),self.bind);self.j.sent(i,'sent')
            self.j.battle(evidence(p.battle()),self.bind);self.j.complete(evidence(p.result()),self.bind)
            i=self.j.intent('result_close',classify(p.result()),evidence(p.result()),self.bind);self.j.sent(i,'sent')
            self.j.acknowledge_close(evidence(p.npc()),self.bind)
        for kind,name in [('select','old'),('challenge','old')]:
            o=p.npc(True,name=name);i=self.j.intent(kind,classify(o),evidence(o),self.bind);self.j.sent(i,'sent')
        self.folder=self.home/'runs'/self.old;self.folder.mkdir(parents=True)
        self.source=dict(run_id=self.old,run_dir=str(self.folder),home=str(self.home),target=self.target,
            settings=dict(task='arena',data_dir=str(self.root),arena_count=9),requested_at=self.started)
        self.status=dict(run_id=self.old,mode='blocked',scene='arena_team',wins=4,arena_requested=9,updated_at=time.time()+1)
        atomic_json(self.folder/'request.json',self.source);atomic_json(self.folder/'status.json',self.status)
        atomic_json(self.folder/'control.json',dict(run_id=self.old,action='run'));(self.folder/'worker.log').write_text('',encoding='utf-8')
        self.request=dict(run_id=self.new,home=str(self.home),instance_base=str(self.home),target=copy.deepcopy(self.target),
            settings=copy.deepcopy(self.source['settings']),requested_at=time.time()+2)
    def prepare(self):return recovery.prepare(self.root,self.request,object())
    def apply(self,plan,*,reading=None,binding=None,age=0):
        o=p.team(name='new');snap=FrameSnapshot(self.image,binding or self.bind,time.monotonic()-age)
        return recovery.apply(plan,snap,o,reading or classify(o),self.request)
    def test_no_active_or_pending_keeps_four_of_nine_and_all_history(self):
        before=read_json(self.j.path);plan=self.prepare();self.assertEqual(plan['mode'],'navigation')
        self.assertEqual(read_json(self.j.path),before)
        report=self.apply(plan);after=read_json(self.j.path)
        self.assertEqual(after['runs'],before['runs']);self.assertEqual(ArenaJournal(self.root,self.old,9).remaining,5)
        self.assertNotIn(self.new,after['runs']);self.assertFalse(report['game_input_sent']);self.assertFalse(report['completion_claimed'])
        for key in ('attempted','completed','entry_dispatches','active','actions','last_cleared'):self.assertEqual(after[key],before[key])
    def test_worker_reconcile_returns_logical_batch_not_new_controller(self):
        with patch('arena_worker.read_observation',return_value=p.team(name='new')):
            resumed=recovery.reconcile(self.root,self.request,object(),lambda:FrameSnapshot(self.image,self.bind,time.monotonic()),Mock())
        self.assertEqual(resumed,self.old)
    def test_resumed_worker_returns_reselects_and_finishes_only_remaining_five(self):
        import shutil
        original=read_json(self.j.path)
        def prepare(root):shutil.copytree(self.j.root,root/'arena')
        first=p.team(name='new');first.visuals.add('arena_native_back');rows=[first]
        for index in range(5):
            name='next '+str(index)
            rows.extend([p.npc(name=name),p.npc(True,name=name),p.team(name=name),p.battle(name=name),p.result(name=name)])
        rows.append(p.npc())
        tr,c,s,_=p.ArenaProgressionTests.exercise(self,rows,requested=9,prepare=prepare,bindings=[self.bind]*len(rows),initial_binding=self.bind,
            patches=[patch('arena_recovery.reconcile',return_value=self.old)])
        self.assertEqual(s['runs'][self.old]['wins'],9);self.assertNotIn('current-frame',s['runs'])
        self.assertEqual(sum(k=='entry' for _,k,_ in tr.inputs),5)
        self.assertEqual(sum(k=='return_to_npc' for _,k,_ in tr.inputs),1)
        self.assertEqual(c.statuses[-1][1]['mode'],'done');self.assertFalse(c.attentions)
        for field in ('attempted','completed','entry_dispatches'):
            for key,value in original[field].items():self.assertEqual(s[field][key],value)
        self.assertEqual(s['actions'][:len(original['actions'])],original['actions'])
        self.assertTrue(all(a.get('controller_run_id')=='current-frame' for a in s['actions'][len(original['actions']):]))

    def test_unknown_or_expired_or_other_window_does_not_consume_quota_plan(self):
        for args in (dict(reading=Reading()),dict(age=6),dict(binding='other')):
            before=self.j.path.read_bytes()
            with self.assertRaises(ValueError):self.apply(self.prepare(),**args)
            self.assertEqual(self.j.path.read_bytes(),before)
    def test_source_state_status_request_or_evidence_tampering_refuses_without_input(self):
        for part in ('state','status','request','evidence'):
            plan=self.prepare();file={'state':self.j.path,'status':self.folder/'status.json','request':self.folder/'request.json',
                'evidence':self.j.root/self.j.state['actions'][-1]['evidence']['image']}[part]
            data=file.read_bytes();file.write_bytes(data+b' ')
            try:
                with self.assertRaises(ValueError):self.apply(plan)
                if part=='evidence':
                    with self.assertRaises(ValueError):self.prepare()
            finally:file.write_bytes(data)
    def test_unknown_navigation_send_or_missing_result_return_cannot_reset_or_resume(self):
        before=read_json(self.j.path)
        for change in ('unknown','missing_close','unsettled','wrong_wins'):
            s=copy.deepcopy(before)
            if change=='unknown':s['actions'][-1]['status']='unknown'
            if change=='missing_close':next(iter(s['completed'].values())).pop('close_evidence')
            if change=='unsettled':next(iter(s['completed'].values()))['opponent']='foreign'
            if change=='wrong_wins':s['runs'][self.old]['wins']=3
            atomic_json(self.j.path,s)
            try:
                with self.assertRaises(ValueError):self.prepare()
            finally:atomic_json(self.j.path,before)
    def test_second_maintenance_actor_keeps_the_same_batch_and_older_navigation(self):
        self.apply(self.prepare());j=ArenaJournal(self.root,self.old,9);j.controller_run_id=self.new
        at=self.request['requested_at']+1
        o=p.team(name='new');ev=j.evidence(FrameSnapshot(self.image,self.bind,99),o,classify(o))
        with patch('arena_journal.time.time',return_value=at):
            ident=j.intent('return_to_npc',classify(o),ev,self.bind);j.sent(ident,'sent')
        folder=self.home/'runs'/self.new;folder.mkdir()
        source=copy.deepcopy(self.request);source['run_dir']=str(folder)
        atomic_json(folder/'request.json',source)
        atomic_json(folder/'status.json',dict(run_id=self.new,mode='blocked',scene='arena_npc',wins=4,arena_requested=9,updated_at=at+1))
        atomic_json(folder/'control.json',dict(run_id=self.new,action='run'));(folder/'worker.log').write_text('',encoding='utf-8')
        self.request=copy.deepcopy(source);self.request.update(run_id='c'*32,requested_at=at+2)
        plan=self.prepare();self.assertEqual(plan['journal'].run_id,self.old)
        self.assertEqual(plan['navigation_ids'],[ident]);self.apply(plan)
        after=read_json(j.path);self.assertEqual(after['runs'][self.old]['wins'],4);self.assertEqual(len(after['runs']),1)
        self.assertEqual(after['actions'],j.state['actions'])

    def test_different_requested_count_is_not_silently_changed(self):
        self.request['settings']['arena_count']=3;before=self.j.path.read_bytes()
        self.assertIsNone(self.prepare());self.assertEqual(self.j.path.read_bytes(),before)
    def test_apply_cannot_be_consumed_twice_and_write_failure_preserves_original_records(self):
        plan=self.prepare();before=self.j.path.read_bytes()
        with patch.object(plan['journal'],'save',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.apply(plan)
        self.assertEqual(self.j.path.read_bytes(),before)
        plan=self.prepare();self.apply(plan)
        with self.assertRaises(ValueError):self.apply(plan)

if __name__=='__main__':unittest.main()
