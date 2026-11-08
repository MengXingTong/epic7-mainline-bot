"""Known-team current-screen starts + exact-run maintenance; synthetic only."""
import copy,hashlib,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from arena_core import classify
from arena_journal import ArenaJournal
from assistant_config import atomic_json,read_json,load_theater_resume_request
from assistant_worker import Control,StopRun
import assistant_control
import test_arena_progression as p


class ArenaCurrentTeamTests(unittest.TestCase):
    def exercise(self,*args,**kwargs):return p.ArenaProgressionTests.exercise(self,*args,**kwargs)
    def test_start_on_known_team_returns_before_select_challenge_and_first_entry(self):
        start=p.team(name='previous');start.visuals.add('arena_native_back')
        tr,c,s,_=self.exercise([start,p.npc(),p.npc(True),p.team()])
        self.assertEqual([k for _,k,_ in tr.inputs],['return_to_npc','select','challenge','entry'])
        self.assertEqual(s['actions'][0]['reason'],'current_screen_start')
        self.assertEqual(s['actions'][0]['input'],'native_back');self.assertFalse(c.attentions)
        self.assertEqual(len(s['attempted']),1);self.assertEqual(s['active']['opponent'],'NPC A')
    def test_full_four_from_current_team_stops_exactly_at_four(self):
        start=p.team(name='previous');start.visuals.add('arena_native_back');rows=[start]
        for _ in range(4):rows.extend([p.npc(),p.npc(True),p.team(),p.battle(),p.result()])
        rows.append(p.npc())
        tr,c,s,_=self.exercise(rows,requested=4)
        self.assertEqual(s['runs']['current-frame']['wins'],4);self.assertEqual(c.statuses[-1][1]['mode'],'done')
        self.assertEqual(sum(k=='entry' for _,k,_ in tr.inputs),4);self.assertEqual(sum(k=='return_to_npc' for _,k,_ in tr.inputs),1)
        self.assertIsNone(s['active']);self.assertIsNone(s['runs']['current-frame']['pending_result'])
    def test_missing_arrow_unknown_modal_defeat_and_resource_do_not_return_or_enter(self):
        for label in ('arrow','确认','战斗失败','购买挑战书'):
            o=p.team();o.visuals.add('arena_native_back')
            if label=='arrow':o.visuals.clear()
            else:o.tokens.append(p.token(label,.5,.5))
            tr,c,s,_=self.exercise([o,o]);self.assertFalse(tr.inputs);self.assertFalse(s['attempted'])
    def test_pending_return_wait_is_reported_instead_of_silent_run(self):
        o=p.team();o.visuals.add('arena_native_back')
        tr,c,s,_=self.exercise([o,o,o]);self.assertEqual(len(tr.inputs),1)
        waits=[a for a,k in c.statuses if k.get('mode')=='waiting_evidence']
        self.assertTrue(waits);self.assertIn('尚未发送开战',waits[-1][0]);self.assertFalse(s['attempted'])
    def test_free_return_response_is_independent_and_bounded_no_spending(self):
        with tempfile.TemporaryDirectory() as root:
            j=ArenaJournal(root,'r',4);r=classify(p.team());ev=dict(captured_at=1)
            for index in range(3):
                with patch('arena_journal.time.time',return_value=10+index*3):
                    i=j.intent('return_to_npc',r,dict(captured_at=index+1),'w');j.sent(i,'sent')
                    self.assertIsNone(j.return_to_npc_context(r,'w',index+1.5))
            with patch('arena_journal.time.time',return_value=30):
                self.assertIsNone(j.return_to_npc_context(r,'w',5))
                with self.assertRaises(ValueError):j.intent('return_to_npc',r,dict(captured_at=5),'w')
            self.assertEqual([a['send_index'] for a in j.state['actions']],[1,2,3]);self.assertFalse(j.state['attempted'])
            self.assertTrue(all(a['return_group']==j.state['actions'][0]['id'] for a in j.state['actions']))
    def test_return_never_reuses_unknown_reserved_stale_or_other_target_intent(self):
        with tempfile.TemporaryDirectory() as root:
            j=ArenaJournal(root,'r',4);r=classify(p.team());i=j.intent('return_to_npc',r,dict(captured_at=1),'w')
            j.sent(i,'unknown');before=copy.deepcopy(j.state)
            with patch('arena_journal.time.time',return_value=time.time()+30):
                self.assertIsNone(j.return_to_npc_context(r,'w',9));self.assertIsNone(j.return_to_npc_context(r,'other',9))
            self.assertEqual(j.state,before)
    def test_existing_sent_entry_prevents_startup_return(self):
        o=p.team();o.visuals.add('arena_native_back')
        tr,c,s,_=self.exercise([p.npc(),p.npc(True),o,o,o])
        self.assertEqual([k for _,k,_ in tr.inputs],['select','challenge','entry'])
        self.assertIsNotNone(s['active']);self.assertEqual(len(s['entry_dispatches']),1)
    def test_slow_first_ocr_drops_stale_frame_before_any_intent_and_uses_next_fresh_frame(self):
        from types import SimpleNamespace
        now=time.monotonic();clock=SimpleNamespace(monotonic=lambda:now,time=time.time)
        tr,c,s,_=self.exercise([p.npc(),p.npc()],timestamps=[now-6,now],patches=[patch('arena_worker.time',clock)])
        self.assertEqual([(i,k) for i,k,_ in tr.inputs],[(2,'select')]);self.assertEqual(len(s['actions']),1)
        self.assertTrue(any(k.get('mode')=='waiting_evidence' for a,k in c.statuses))
    def test_expired_entry_frame_never_reserves_resource_or_bypasses_fresh_cost_check(self):
        from types import SimpleNamespace
        now=time.monotonic();current=[now];clock=SimpleNamespace(monotonic=lambda:current[0],time=time.time)
        rows=[p.npc(),p.npc(True),p.team(),p.team(cost='1/0')];index=[0]
        def read(*args):
            i=index[0];index[0]+=1;current[0]=now+(6 if i>=2 else 0);return rows[i]
        tr,c,s,_=self.exercise(rows,timestamps=[now-2,now-1,now,now+6],
            patches=[patch('arena_worker.time',clock),patch('arena_worker.read_observation',side_effect=read)])
        self.assertEqual([k for _,k,_ in tr.inputs],['select','challenge'])
        self.assertFalse(s['attempted']);self.assertTrue(c.attentions)

    def test_return_write_failure_or_send_uncertainty_does_not_enter(self):
        o=p.team();o.visuals.add('arena_native_back')
        for failure in ('return_to_npc','unknown_return_to_npc'):
            tr,c,s,_=self.exercise([o,o],fail_on=failure,expect_error=RuntimeError if failure.startswith('unknown') else None)
            self.assertEqual(len(tr.inputs),1);self.assertFalse(s['attempted'])
            self.assertEqual(s['actions'][0]['status'],'unknown' if failure.startswith('unknown') else 'not_sent')


class ArenaLocalMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name).resolve();self.root=self.home/'profile';self.run='a'*32
        self.folder=self.home/'runs'/self.run;self.folder.mkdir(parents=True)
        self.j=ArenaJournal(self.root,self.run,4)
        self.request=dict(run_id=self.run,run_dir=str(self.folder),home=str(self.home),settings=dict(task='arena',data_dir=str(self.root),arena_count=4,observe=False),
            target=dict(client='mumu',serial='selected',package='game'),requested_at=time.time()-30)
        self.marker=dict(run_id=self.run,run_dir=str(self.folder),worker_pid=111)
        atomic_json(self.home/'active-run.json',self.marker);atomic_json(self.folder/'request.json',self.request)
        atomic_json(self.folder/'status.json',dict(run_id=self.run,mode='stopped',wins=0,arena_requested=4))
        atomic_json(self.folder/'control.json',dict(run_id=self.run,action='stop',command_id='original-stop'))
        self.leases=Mock();self.leases.acquire.return_value=object()
        self.patchers=[patch('assistant_instances.NamedLeases',return_value=self.leases),patch('assistant_config.process_is_alive',return_value=False),
            patch('assistant_config.validate_run',return_value=(self.root,{}))]
        for patcher in self.patchers:patcher.start();self.addCleanup(patcher.stop)
    def test_exact_request_run_quota_history_and_target_survive_local_reload(self):
        original=(self.folder/'request.json').read_bytes();state=self.j.path.read_bytes()
        def run(effective):
            self.assertEqual(effective['run_id'],self.run);self.assertEqual(effective['settings']['arena_count'],4)
            self.assertEqual(effective['target'],self.request['target']);Control(effective).check()
            self.assertEqual(read_json(self.home/'active-run.json')['worker_pid'],os.getpid())
            print('synthetic local maintenance, no game input')
        with patch('assistant_worker.run_request',side_effect=run) as worker:assistant_control.reload_original_arena(self.home,self.run)
        worker.assert_called_once();self.assertEqual((self.folder/'request.json').read_bytes(),original)
        self.assertEqual(self.j.path.read_bytes(),state);self.leases.release.assert_called_once()
        reports=list(self.folder.glob('arena-local-reload-*.json'));self.assertEqual(len(reports),1)
        r=read_json(reports[0]);self.assertFalse(r['quota_reset']);self.assertFalse(r['request_replaced'])
    def test_current_marker_change_revokes_maintenance_actor(self):
        def run(effective):
            Control(effective).check();atomic_json(self.home/'active-run.json',dict(self.marker,run_id='b'*32))
            with self.assertRaises(StopRun):Control(effective).check()
        with patch('assistant_worker.run_request',side_effect=run):assistant_control.reload_original_arena(self.home,self.run)
    def test_existing_stop_and_pause_remain_effective(self):
        from assistant_worker import PauseRun
        def run(effective):
            for action,exc in [('stop',StopRun),('pause',PauseRun)]:
                atomic_json(self.folder/'control.json',dict(run_id=self.run,action=action))
                with self.assertRaises(exc):Control(effective).check()
        with patch('assistant_worker.run_request',side_effect=run):assistant_control.reload_original_arena(self.home,self.run)
    def test_live_worker_nonstopped_source_and_stop_marker_refuse_reload(self):
        original=read_json(self.folder/'status.json')
        for reason in ('live','status','STOP'):
            if reason=='live':self.patchers[1].stop();live=patch('assistant_config.process_is_alive',return_value=True);live.start()
            if reason=='status':atomic_json(self.folder/'status.json',dict(original,mode='run'))
            if reason=='STOP':(self.root/'STOP').write_text('stop',encoding='utf-8')
            try:
                before=(self.folder/'control.json').read_bytes()
                with patch('assistant_worker.run_request') as worker:
                    with self.assertRaises(ValueError):assistant_control.reload_original_arena(self.home,self.run)
                worker.assert_not_called();self.assertEqual((self.folder/'control.json').read_bytes(),before)
            finally:
                if reason=='live':live.stop();self.patchers[1].start()
                if reason=='status':atomic_json(self.folder/'status.json',original)
                if reason=='STOP':(self.root/'STOP').unlink()
    def test_blocked_free_navigation_can_reload_without_fabricating_sent_or_an_attempt(self):
        r=classify(p.npc(True))
        for kind in ('select','challenge'):
            i=self.j.intent(kind,r,dict(captured_at=1),'window');self.j.sent(i,'unknown' if kind=='challenge' else 'sent')
        atomic_json(self.folder/'status.json',dict(run_id=self.run,mode='blocked',scene='arena_npc',wins=0,arena_requested=4))
        state=self.j.path.read_bytes()
        with patch('assistant_worker.run_request') as worker:assistant_control.reload_original_arena(self.home,self.run)
        worker.assert_called_once();self.assertEqual(self.j.path.read_bytes(),state)
    def test_blocked_unknown_resource_entry_never_uses_free_navigation_reload(self):
        r=classify(p.team())
        for kind in ('select','challenge','entry'):
            i=self.j.intent(kind,r,dict(captured_at=1),'window');self.j.sent(i,'unknown' if kind=='entry' else 'sent')
        atomic_json(self.folder/'status.json',dict(run_id=self.run,mode='blocked',scene='arena_team',wins=0,arena_requested=4))
        with patch('assistant_worker.run_request') as worker:
            with self.assertRaises(ValueError):assistant_control.reload_original_arena(self.home,self.run)
        worker.assert_not_called()

    def test_absent_original_batch_does_not_create_empty_quota(self):
        s=read_json(self.j.path);s['runs'].clear();atomic_json(self.j.path,s);before=self.j.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'不能新建'):load_theater_resume_request(self.run,self.home)
        self.assertEqual(self.j.path.read_bytes(),before)
    def test_new_run_id_or_wrong_task_or_second_reload_refuses_before_control_change(self):
        before=(self.folder/'control.json').read_bytes()
        with self.assertRaises(ValueError):assistant_control.reload_original_arena(self.home,'b'*32)
        self.leases.acquire.return_value=None
        with self.assertRaises(ValueError):assistant_control.reload_original_arena(self.home,self.run)
        self.leases.acquire.return_value=object();atomic_json(self.folder/'request.json',dict(self.request,settings=dict(self.request['settings'],task='mainline')))
        with self.assertRaises(ValueError):assistant_control.reload_original_arena(self.home,self.run)
        self.assertEqual((self.folder/'control.json').read_bytes(),before)
    def test_regular_restart_still_cannot_repeat_counted_task(self):
        with patch.object(assistant_control,'HOME',self.home),patch('sys.argv',['assistant_control.py','--instance','1','restart']):
            with self.assertRaises(ValueError):assistant_control.main()
        self.assertFalse((self.home/'gui-command.json').exists())
    def test_failed_receipt_write_never_activates_worker(self):
        before=(self.folder/'control.json').read_bytes();marker=(self.home/'active-run.json').read_bytes()
        original=assistant_control.atomic_json
        def save(path,data):
            if Path(path).name.startswith('arena-local-reload-'):raise OSError('cannot save source receipt')
            return original(path,data)
        with patch.object(assistant_control,'atomic_json',side_effect=save),patch('assistant_worker.run_request') as worker:
            with self.assertRaises(OSError):assistant_control.reload_original_arena(self.home,self.run)
        worker.assert_not_called();self.assertEqual((self.folder/'control.json').read_bytes(),before)
        self.assertEqual((self.home/'active-run.json').read_bytes(),marker)

class ArenaBusyStartRestoreTests(unittest.TestCase):
    def setUp(self):
        ArenaLocalMaintenanceTests.setUp(self)
        self.source_marker=copy.deepcopy(self.marker);self.current='b'*32;self.current_folder=self.home/'runs'/self.current;self.current_folder.mkdir()
        now=time.time();self.current_request=copy.deepcopy(self.request)
        self.current_request.update(run_id=self.current,run_dir=str(self.current_folder),requested_at=now-3)
        atomic_json(self.current_folder/'request.json',self.current_request)
        atomic_json(self.current_folder/'status.json',dict(run_id=self.current,mode='blocked',scene='—',wins=0,
            status='该游戏窗口/模拟器已由另一个助手控制；请选择其他客户端实例。'))
        atomic_json(self.current_folder/'control.json',dict(run_id=self.current,action='run'))
        self.marker=dict(run_id=self.current,run_dir=str(self.current_folder),worker_pid=222);atomic_json(self.home/'active-run.json',self.marker)
        self.receipt=self.folder/'arena-local-reload-source.json'
        atomic_json(self.receipt,dict(run_id=self.run,phase='finished',at=now-5,finished_at=now-1,
            final_status=read_json(self.folder/'status.json'),active_marker=self.source_marker,
            source_files={str(self.folder/'request.json'):hashlib.sha256((self.folder/'request.json').read_bytes()).hexdigest()}))
    def restore(self):return assistant_control.restore_arena_after_busy_start(self.home,self.run,self.current)
    def test_proven_collision_restores_only_existing_batch_then_standard_reload(self):
        before=self.j.path.read_bytes();request=(self.current_folder/'request.json').read_bytes();status=(self.current_folder/'status.json').read_bytes()
        receipt=self.restore();self.assertFalse(read_json(receipt)['game_input_sent'])
        self.assertEqual(read_json(self.home/'active-run.json'),self.source_marker)
        with patch('assistant_worker.run_request') as worker:assistant_control.reload_original_arena(self.home,self.run)
        self.assertEqual(worker.call_args.args[0]['settings']['arena_count'],4)
        self.assertEqual(worker.call_args.args[0]['run_id'],self.run)
        self.assertEqual(self.j.path.read_bytes(),before);self.assertEqual((self.current_folder/'request.json').read_bytes(),request)
        self.assertEqual((self.current_folder/'status.json').read_bytes(),status)
    def test_other_target_count_profile_or_nonbusy_failure_is_not_a_collision(self):
        original=copy.deepcopy(self.current_request);before=read_json(self.home/'active-run.json')
        for kind in ('count','target','profile','status'):
            r=copy.deepcopy(original)
            if kind=='count':r['settings']['arena_count']=5
            if kind=='target':r['target']['serial']='other'
            if kind=='profile':r['settings']['data_dir']=str(self.home/'other')
            if kind=='status':atomic_json(self.current_folder/'status.json',dict(run_id=self.current,mode='blocked',scene='—',wins=0,status='other'))
            atomic_json(self.current_folder/'request.json',r)
            with self.assertRaises(ValueError):self.restore()
            self.assertEqual(read_json(self.home/'active-run.json'),before)
            atomic_json(self.current_folder/'request.json',original)
    def test_missing_or_ambiguous_receipts_do_not_pick_a_batch(self):
        data=self.receipt.read_bytes();self.receipt.unlink()
        with self.assertRaises(ValueError):self.restore()
        self.receipt.write_bytes(data);(self.folder/'arena-local-reload-copy.json').write_bytes(data)
        with self.assertRaises(ValueError):self.restore()
        self.assertEqual(read_json(self.home/'active-run.json'),self.marker)
    def test_existing_new_batch_or_unsettled_entry_prevents_restore(self):
        before=read_json(self.j.path);data=copy.deepcopy(before);data['runs'][self.current]=dict(requested=4,wins=0)
        atomic_json(self.j.path,data)
        with self.assertRaises(ValueError):self.restore()
        atomic_json(self.j.path,before);r=classify(p.team())
        for kind in ('select','challenge','entry'):
            i=self.j.intent(kind,r,dict(captured_at=1),'window');self.j.sent(i,'sent')
        with self.assertRaises(ValueError):self.restore()
        self.assertEqual(read_json(self.home/'active-run.json'),self.marker)
    def test_active_source_or_new_stop_marker_prevents_restore(self):
        with patch('assistant_config.process_is_alive',side_effect=lambda pid:pid==111):
            with self.assertRaises(ValueError):self.restore()
        (self.root/'STOP').write_text('stop',encoding='utf-8')
        with self.assertRaises(ValueError):self.restore()
        self.assertEqual(read_json(self.home/'active-run.json'),self.marker)
    def test_restore_receipt_write_failure_does_not_change_marker_or_control(self):
        before=(self.folder/'control.json').read_bytes();original=assistant_control.atomic_json
        def write(path,data):
            if Path(path).name.startswith('arena-busy-start-restore-'):raise OSError('cannot write proof')
            return original(path,data)
        with patch.object(assistant_control,'atomic_json',side_effect=write):
            with self.assertRaises(OSError):self.restore()
        self.assertEqual((self.folder/'control.json').read_bytes(),before);self.assertEqual(read_json(self.home/'active-run.json'),self.marker)


class ArenaFrameExpiryTypeTests(unittest.TestCase):
    def transport(self,age):
        from PIL import Image
        from assistant_transport import UnifiedTransport,FrameSnapshot
        tr=UnifiedTransport.__new__(UnifiedTransport);tr.check=lambda:None
        f=FrameSnapshot(Image.new('RGB',(1600,900)),'window',time.monotonic()-age)
        tr.frame=f;tr.ensure=lambda:'window';return tr,f
    def test_old_unconsumed_frame_has_real_frame_expired_type(self):
        from pc_backend import FrameExpired
        tr,f=self.transport(6)
        with self.assertRaises(FrameExpired):tr._fresh(f)
        self.assertIs(tr.frame,f)
    def test_consumed_frame_and_geometry_change_are_not_retriable_age(self):
        from pc_backend import FrameExpired,PcSafetyError
        for changed in ('consumed','geometry'):
            tr,f=self.transport(0)
            if changed=='consumed':tr.frame=None
            else:tr.ensure=lambda:'other'
            with self.assertRaises(PcSafetyError) as caught:tr._fresh(f)
            self.assertNotIsInstance(caught.exception,FrameExpired)


if __name__=='__main__':unittest.main()
