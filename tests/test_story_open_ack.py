"""Free UI message acknowledgement is not a stage retry or a completed result."""
import copy,hashlib,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
import story_open_ack as ack
from entry_journal import reserve_entry,finish_dispatch
from test_story_only_nodes import frame,fake_runner
from pc_backend import WindowSnapshot,TapNotSent
from task_blockers import TaskAttention


class StoryOpenAckTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.root_patch=patch.object(runner,'ROOT',self.root);self.root_patch.start()
        (self.root/'evidence').mkdir();(self.root/'evidence'/'original.png').write_bytes(b'original synthetic evidence')
        self.r=fake_runner(frame());self.r.run_id='original-run';self.r.pc=None
        self.r.cfg.update(serial='known-emulator',package='known-game')
        d=copy.deepcopy(self.r.map_ticket(self.r.frame)[0]);self.key=d['key']
        d['evidence']='evidence/original.png'
        original=dict(d,cost=0,entry_kind='story_only',start_epoch=time.time()-30)
        dispatch=reserve_entry(self.r.s,self.key,original);self.r.s['active']=copy.deepcopy(original)
        self.record=ack.register_open(self.r,dispatch);finish_dispatch(dispatch,'sent');dispatch['finished_at']-=10
        self.original_dispatch=copy.deepcopy(dispatch);self.old_attempt=copy.deepcopy(self.r.s['attempted'])
        self.rows=[copy.deepcopy(d),dict(stage=d['stage']+1,locked=True)]
        self.r.map_ticket=Mock(return_value=(copy.deepcopy(d),self.rows,'未通关蓝色当前节点'))
        self.r.attention=Mock(side_effect=lambda *a:(_ for _ in ()).throw(TaskAttention(*a)))
        self.events=[dict(kind='action',action=ack.OPEN_ACTION,stage=self.key)]
        self.write_events()
        self.r.action.side_effect=lambda action,target:self.add_event(dict(kind='action',action=action,stage=self.key))
        self.controller=ack.StoryOpenAcknowledgement(self.r)
    def tearDown(self):self.root_patch.stop();self.temp.cleanup()
    def write_events(self):(self.root/'events.jsonl').write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in self.events),encoding='utf-8')
    def add_event(self,e):self.events.append(e);self.write_events()
    def fresh(self,offset=0):
        f=frame();f.at=time.time()+offset;self.r.frame=f;return f
    def pair(self):
        self.controller.step(self.fresh(-.25));return self.controller.step(self.fresh())
    def unchanged(self):
        self.assertEqual(self.r.s['attempted'],self.old_attempt)
        self.assertEqual(self.r.s['entry_dispatches'][self.key],[self.original_dispatch])
        self.assertEqual(self.r.s['completed'],{})
    def notice_chain_fixture(self):
        from datetime import datetime,timezone
        from free_notices import FreeNoticeController
        self.clock=time.time()+1
        clock=patch('time.time',side_effect=lambda:self.clock);clock.start();self.addCleanup(clock.stop)
        self.r.story_open_ack=self.controller;self.r.free_notices=FreeNoticeController(self.r)
        def log(kind,**fields):
            self.add_event(dict(time=datetime.fromtimestamp(self.clock,timezone.utc).isoformat(timespec='seconds'),kind=kind,**fields))
        events=patch.object(runner,'event',side_effect=log);events.start();self.addCleanup(events.stop)
        counter=[0]
        def evidence(label):
            counter[0]+=1;path=self.root/'evidence'/f'notice-{counter[0]}.png'
            path.write_bytes(runner.cv2.imencode('.png',self.r.frame.image)[1].tobytes());return str(path.relative_to(self.root))
        self.r.evidence.side_effect=evidence
        def action(label,target):
            w,h=self.r.frame.raw_size
            log('action',action=label,stage=self.key,xy=[round(target['x']*w/1600),round(target['y']*h/900)])
        self.r.action.side_effect=action
    def chain_step(self,f=None):
        self.clock+=.3;f=f or frame();f.at=self.clock;self.r.frame=f;return self.r.step(f)
    def close_notice_chain(self):
        from test_tutorial_completed_notice import notice
        from datetime import datetime,timezone
        self.chain_step(notice())
        # Set up an observed departure without also invoking the next map action.
        self.clock+=.3;f=frame();f.at=self.clock;self.r.frame=f
        self.add_event(dict(time=datetime.fromtimestamp(self.clock,timezone.utc).isoformat(timespec='seconds'),kind='screen',screen='map',stage=self.key))
        self.r.last_mode='map';self.r.free_notices.observe_scene('map',f)
        return self.r.s['free_notice_dismissals']['occurrences'][-1]
    def test_full_production_notice_close_return_and_story_acceptance_chain(self):
        self.notice_chain_fixture();snapshots=[];self.r.save.side_effect=lambda:snapshots.append(copy.deepcopy(self.r.s))
        notice=self.close_notice_chain()
        self.assertEqual(notice['phase'],'dismissed');self.assertEqual(self.r.action.call_count,1)
        self.assertEqual(self.record['messages'],[]);self.chain_step()
        self.assertEqual(self.r.action.call_count,2);message=self.record['messages'][0]
        self.assertEqual(message['source']['free_notice_receipts'][0]['occurrence_id'],notice['id'])
        reserved=[s for s in snapshots if s['story_open_acknowledgements'][self.original_dispatch['id']]['messages']][0]
        self.assertEqual(reserved['story_open_acknowledgements'][self.original_dispatch['id']]['messages'][0]['status'],'reserved')
        self.assertEqual(notice['entry_context']['original_dispatch_id'],self.original_dispatch['id'])
        self.controller.observe_scene('story',self.r.frame)
        self.assertIsNone(self.controller.step(self.fresh(-.25)));self.assertIsNone(self.controller.step(self.fresh()))
        self.assertEqual(self.r.action.call_count,2);self.assertEqual(self.record['phase'],'accepted');self.unchanged()
    def test_notice_chain_critical_reservation_and_evidence_failure_prevent_entry_input(self):
        self.notice_chain_fixture();self.close_notice_chain();self.r.save.side_effect=OSError('critical state denied')
        with self.assertRaises(OSError):self.chain_step()
        self.assertEqual(self.r.action.call_count,1);self.unchanged()
    def test_notice_chain_send_evidence_failure_prevents_entry_input(self):
        self.notice_chain_fixture();self.close_notice_chain();self.r.evidence.side_effect=OSError('critical evidence denied')
        with self.assertRaises(OSError):self.chain_step()
        self.assertEqual(self.r.action.call_count,1);self.assertEqual(self.record['messages'],[]);self.unchanged()
    def test_notice_ocr_gap_and_reappearance_are_not_mistaken_for_playback(self):
        from test_tutorial_completed_notice import notice
        self.notice_chain_fixture();self.chain_step(notice())
        self.add_event(dict(kind='screen',screen='unknown_dialog',stage=self.key))
        self.r.last_mode='unknown_dialog'
        self.chain_step(notice());self.chain_step(notice());self.chain_step();self.chain_step();self.chain_step()
        self.assertEqual(self.r.action.call_count,2);self.unchanged()

    def test_first_known_return_map_can_continue_without_second_disappearance_frame(self):
        from test_tutorial_completed_notice import notice
        self.notice_chain_fixture();self.chain_step(notice())
        self.assertEqual(self.chain_step(),(True,.25));self.r.attention.assert_not_called()
        self.assertEqual(len(self.record['messages']),1);self.assertEqual(self.r.action.call_count,2)
        self.unchanged()
    def test_original_v1_notice_receipt_is_verified_without_rewriting_or_new_permission(self):
        self.notice_chain_fixture();notice=self.close_notice_chain()
        notice.pop('entry_context');notice.pop('disappearance_observations');before=copy.deepcopy(notice)
        source=ack.trace_source(self.r,self.record)
        self.assertEqual(source['free_notice_receipts'][0]['occurrence_id'],notice['id'])
        self.assertEqual(notice,before);self.chain_step();self.assertEqual(self.r.action.call_count,2);self.unchanged()
    def test_notice_receipt_mutations_do_not_authorize_an_entry_message(self):
        self.notice_chain_fixture();notice=self.close_notice_chain();saved=copy.deepcopy(notice)
        mutations={
            'run':lambda n:n.update(run_id='foreign-run'),
            'entry':lambda n:n['entry_context'].update(key='foreign-stage'),
            'dispatch':lambda n:n['entry_context'].update(original_dispatch_id='foreign'),
            'attempt':lambda n:n['entry_context'].update(original_sha256='changed'),
            'window':lambda n:n['binding'].update(window={'pid':7}),
            'geometry':lambda n:n['binding'].update(raw_size=[1045,588]),
            'body':lambda n:n.update(body='unknown.already_completed_tutorial'),
            'kind':lambda n:n.update(kind='unknown'),
            'still_visible':lambda n:n.update(phase='awaiting_disappearance'),
            'other_departure':lambda n:n.update(gone_scene='story'),
            'unknown_send':lambda n:n['messages'][0].update(status='unknown'),
            'not_sent':lambda n:n['messages'][0].update(status='not_sent'),
            'before_source':lambda n:n['messages'][0]['observations'][0].update(captured_at=0),
            'weak_target':lambda n:n['messages'][0]['observations'][0]['target'].update(score=.979),
            'missing_image':lambda n:n['messages'][0]['observations'][0].update(evidence='evidence/missing.png'),
            'outside_image':lambda n:n['messages'][0]['observations'][0].update(evidence='../outside.png'),
            'changed_pixels':lambda n:n['messages'][0]['observations'][0].update(image_sha256='different'),
            'weak_departure':lambda n:n['disappearance_observations'][0].update(captured_at=0),
            'changed_departure':lambda n:n['disappearance_observations'][0].update(image_sha256='different')}
        for name,mutate in mutations.items():
            with self.subTest(name=name):
                notice.clear();notice.update(copy.deepcopy(saved));mutate(notice)
                with self.assertRaises(ValueError):ack.trace_source(self.r,self.record)
                self.assertEqual(self.record['messages'],[]);self.unchanged()
        notice.clear();notice.update(saved)
    def test_notice_label_or_close_action_without_matched_receipt_never_resends(self):
        from free_notices import CLOSE_ACTION
        for event in (dict(kind='screen',screen='tutorial_completed_notice',stage=self.key),
                      dict(kind='action',action=CLOSE_ACTION,stage=self.key)):
            with self.subTest(event=event):
                self.events=[dict(kind='action',action=ack.OPEN_ACTION,stage=self.key),event];self.write_events()
                with self.assertRaises(ValueError):ack.trace_source(self.r,self.record)
        self.r.action.assert_not_called();self.unchanged()
    def test_notice_close_wrong_target_stage_time_duplicate_or_extra_input_veto(self):
        self.notice_chain_fixture();self.close_notice_chain();original=copy.deepcopy(self.events)
        from free_notices import CLOSE_ACTION
        index=next(i for i,e in enumerate(self.events) if e.get('action')==CLOSE_ACTION)
        for mode in ('xy','stage','time','duplicate','other_input','story','battle','settlement','defeat','back','drag'):
            with self.subTest(mode=mode):
                self.events=copy.deepcopy(original)
                if mode=='xy':self.events[index]['xy']=[1,2]
                elif mode=='stage':self.events[index]['stage']='other'
                elif mode=='time':self.events[index]['time']='2000-01-01T00:00:00+00:00'
                elif mode=='duplicate':self.events.insert(index,copy.deepcopy(self.events[index]))
                elif mode=='other_input':self.events.append(dict(kind='action',stage=self.key,action='unknown'))
                elif mode in ('back','drag'):self.events.append(dict(kind=mode))
                else:self.events.append(dict(kind='screen',stage=self.key,screen=mode))
                self.write_events()
                with self.assertRaises(ValueError):ack.trace_source(self.r,self.record)
                self.assertEqual(self.record['messages'],[]);self.unchanged()
    def test_notice_evidence_pixel_corruption_and_persistent_modal_chrome_veto(self):
        self.notice_chain_fixture();notice=self.close_notice_chain()
        path=self.root/notice['messages'][0]['observations'][0]['evidence'];original=path.read_bytes();path.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):ack.trace_source(self.r,self.record)
        path.write_bytes(original)
        # Legacy disappearance receipts still require genuine modal absence.
        notice.pop('disappearance_observations');path=self.root/notice['disappearance_evidence']
        image=runner.cv2.imread(str(path));image[254:256,:]=180;image[644:646,:]=180
        path.write_bytes(runner.cv2.imencode('.png',image)[1].tobytes())
        with self.assertRaises(ValueError):ack.trace_source(self.r,self.record)
        self.assertEqual(self.record['messages'],[]);self.unchanged()
    def test_second_notice_after_original_response_stays_in_same_bounded_chain(self):
        self.notice_chain_fixture();self.close_notice_chain();self.chain_step()
        self.clock+=5;self.close_notice_chain();self.chain_step()
        self.assertEqual(len(self.record['messages']),2)
        self.assertEqual(len(self.record['messages'][-1]['source']['free_notice_receipts']),2)
        self.assertEqual(self.r.action.call_count,4);self.unchanged()
        self.clock+=5
        self.chain_step();self.r.attention.assert_not_called();self.assertEqual(self.r.action.call_count,4)
    def test_notice_receipt_does_not_relax_paid_archived_or_wrong_run_entry_guard(self):
        self.notice_chain_fixture();self.close_notice_chain();original=copy.deepcopy(self.r.s)
        for mode in ('paid','archived','new_run','completed','playback'):
            with self.subTest(mode=mode):
                self.r.s=copy.deepcopy(original);self.r.run_id='original-run'
                if mode=='paid':self.r.s['active']['cost']=8
                if mode=='archived':self.r.s['unresolved_entries']=[dict(entry=copy.deepcopy(self.r.s['active']))]
                if mode=='new_run':self.r.run_id='different-run'
                if mode=='completed':self.r.s['completed'][self.key]={}
                if mode=='playback':self.r.s['active']['playback_observed_at']='observed'
                with self.assertRaises(ValueError):ack.trace_source(self.r,self.record)
        self.assertEqual(self.r.action.call_count,1)

    def test_production_runner_map_step_uses_response_chain_without_reopening_entry(self):
        self.r.story_open_ack=self.controller
        self.r.step(self.fresh(-.25));self.r.action.assert_called_once()
        self.r.step(self.fresh());self.r.action.assert_called_once();self.unchanged()
    def test_first_production_open_registers_awaiting_acceptance_before_send(self):
        r=fake_runner(frame());r.run_id='new-run';r.pc=None;r.cfg.update(serial='known',package='known')
        d=copy.deepcopy(self.r.map_ticket.return_value[0]);r.ticket=copy.deepcopy(d)
        before=[];r.save.side_effect=lambda:before.append(copy.deepcopy(r.s))
        def fresh_target():r.frame=frame();return r.frame
        r.capture=Mock(side_effect=fresh_target)
        r.open_story_node(d,runner.mainline_map_control(r.frame)['target'])
        record=next(iter(before[0]['story_open_acknowledgements'].values()))
        self.assertEqual(record['phase'],'awaiting_acceptance');self.assertEqual(record['run_id'],'new-run')
        self.assertEqual(before[0]['entry_dispatches'][self.key][0]['status'],'reserved')
        r.action.assert_called_once();self.assertEqual(r.s['completed'],{})
    def test_initial_register_is_before_send_and_never_completed(self):
        self.assertEqual(self.record['phase'],'awaiting_acceptance');self.assertEqual(self.record['messages'],[])
        self.unchanged()
    def test_lost_free_ui_message_uses_one_current_frame_in_original_bounded_chain(self):
        snapshots=[];self.r.save.side_effect=lambda:snapshots.append(copy.deepcopy(self.r.s))
        first=self.fresh(-.25);self.controller.step(first);self.r.action.assert_called_once()
        self.controller.step(first);self.controller.step(self.fresh());self.r.action.assert_called_once()
        messages=self.record['messages'];self.assertEqual(len(messages),1);self.assertEqual(messages[0]['status'],'sent')
        before=[s for s in snapshots if s['story_open_acknowledgements'][self.original_dispatch['id']]['messages']][0]
        self.assertEqual(before['story_open_acknowledgements'][self.original_dispatch['id']]['messages'][0]['status'],'reserved')
        self.assertEqual(len(messages[0]['observations']),1);self.unchanged()
    def test_original_reservation_never_allows_additional_messages(self):
        self.r.s['entry_dispatches'][self.key][0]['status']='reserved';self.pair();self.r.action.assert_not_called()
    def test_wait_for_ack_does_not_immediately_click_again(self):
        self.pair();self.pair();self.assertEqual(self.r.action.call_count,1);self.unchanged()
    def test_bounded_free_ui_messages_then_observe_without_defeat_or_manual_attention(self):
        self.pair();self.record['messages'][0]['sent_at']-=10
        self.pair();self.record['messages'][1]['sent_at']-=10
        self.pair();self.r.attention.assert_not_called()
        self.assertEqual(self.r.action.call_count,2);self.assertEqual(self.r.observation_wait['code'],'story_open_response');self.unchanged()
    def test_acceptance_scene_latches_without_completing(self):
        for scene in ack.ACCEPTED_SCENES:
            with self.subTest(scene=scene):
                self.record['phase']='awaiting_acceptance';self.controller.observe_scene(scene,self.r.frame)
                self.assertEqual(self.record['phase'],'accepted');self.pair();self.r.action.assert_not_called();self.unchanged()
    def test_resources_failure_chat_and_client_flow_block_additional_messages(self):
        for scene in ack.BLOCKED_SCENES:
            with self.subTest(scene=scene):
                self.record['phase']='awaiting_acceptance';self.controller.observe_scene(scene,self.r.frame)
                self.assertEqual(self.record['phase'],'blocked');self.pair();self.r.action.assert_not_called()
    def test_unknown_current_page_is_zero_input_but_next_known_page_needs_no_pair(self):
        f=self.fresh();self.controller.observe_scene('unknown_dialog',f)
        with patch.object(runner,'classify',return_value='unknown_dialog'):
            self.controller.step(f);self.r.action.assert_not_called()
        self.controller.step(self.fresh());self.r.action.assert_called_once();self.unchanged()
    def test_completed_archived_paid_wrong_run_and_prior_entry_evidence_reject(self):
        state=copy.deepcopy(self.r.s)
        for mode in ('completed','archived','paid','run','playback','battle','defeat','outcome','other_reopen','history_hash'):
            with self.subTest(mode=mode):
                self.r.s=copy.deepcopy(state);self.r.run_id='original-run';self.controller.pending=None
                if mode=='completed':self.r.s['completed'][self.key]={}
                if mode=='archived':self.r.s['unresolved_entries']=[dict(entry=copy.deepcopy(self.r.s['active']))]
                if mode=='paid':self.r.s['active']['cost']=8
                if mode=='run':self.r.run_id='new-run'
                if mode=='playback':self.r.s['active']['playback_observed_at']='observed'
                if mode=='battle':self.r.s['active']['battle_seen']=123
                if mode=='defeat':self.r.s['active']['defeat_seen']=123
                if mode=='outcome':self.r.s['active']['outcome']='defeat'
                if mode=='other_reopen':self.r.s['story_reopen_authorizations']=[dict(key=self.key)]
                if mode=='history_hash':self.r.s['attempted'][self.key]['name']='changed'
                self.pair();self.r.action.assert_not_called()
    def test_changed_original_preflight_never_resends(self):
        (self.root/'evidence'/'original.png').write_bytes(b'changed');self.pair();self.r.action.assert_not_called()
    def test_other_input_and_any_actual_scene_trace_never_resends(self):
        for event in (dict(kind='back'),dict(kind='drag'),dict(kind='completed'),dict(kind='stop'),dict(kind='action',action='unknown',stage=self.key),
                      *[dict(kind='screen',screen=s,stage=self.key) for s in ('story','battle','settlement','defeat','network_error')]):
            with self.subTest(event=event):
                self.events=[dict(kind='action',action=ack.OPEN_ACTION,stage=self.key),event];self.write_events();self.pair();self.r.action.assert_not_called()
    def test_unknown_no_input_trace_can_reobserve_known_unchanged_entry(self):
        self.add_event(dict(kind='screen',screen='unknown_dialog',stage=self.key));self.pair();self.r.action.assert_called_once();self.unchanged()
    def test_locked_changed_completed_or_unlocked_successor_map_does_not_resend(self):
        original=copy.deepcopy(self.r.map_ticket.return_value)
        for mode in ('wrong','locked','clear','stars','next_unlocked','next_missing','weak','battle_control'):
            with self.subTest(mode=mode):
                self.controller.pending=None;d,rows,proof=copy.deepcopy(original);self.r.map_ticket.return_value=(d,rows,proof)
                if mode=='wrong':d['key']='other'
                if mode=='locked':d['locked']=True
                if mode=='clear':d['clear_badge']=True
                if mode=='stars':d['star_count']=3
                if mode=='next_unlocked':rows[1]['locked']=False
                if mode=='next_missing':rows.pop()
                f=self.fresh(-.25)
                if mode=='weak':f.words[-1]['score']=.979
                if mode=='battle_control':f.words[-1]['text']='准备战斗'
                self.controller.step(f)
                f=self.fresh()
                if mode=='weak':f.words[-1]['score']=.979
                if mode=='battle_control':f.words[-1]['text']='准备战斗'
                self.controller.step(f);self.r.action.assert_not_called()
    def test_stale_detached_or_mismatched_geometry_never_resends(self):
        self.controller.step(self.fresh(-4));self.r.action.assert_not_called()
        detached=frame();self.controller.step(detached);self.r.action.assert_not_called()
        # Changing the client binding is still prohibited; no first positive input was sent.
        f=self.fresh();f.raw_size=(1045,588)
        self.controller.step(f);self.r.action.assert_not_called()
    def test_window_lifetime_or_position_change_rejects(self):
        self.r.pc=Mock();self.r.pc.frame_window=WindowSnapshot(1,2,'game.exe',3,10,20,1600,900)
        self.record['binding']=ack.binding(self.r)
        for change in ('created','x','dpi'):
            with self.subTest(change=change):
                from dataclasses import replace
                original=self.r.pc.frame_window;self.r.pc.frame_window=replace(original,**{change:getattr(original,change)+1})
                self.pair();self.r.action.assert_not_called();self.r.pc.frame_window=original
    def test_critical_save_and_evidence_failure_prevents_send(self):
        self.r.save.side_effect=OSError('state denied')
        with self.assertRaises(OSError):self.pair()
        self.r.action.assert_not_called()
        # Failed reserved intent remains consumed even in memory; no retry.
        self.r.save.side_effect=None;self.pair();self.r.action.assert_not_called()
    def test_observation_evidence_failure_never_inputs(self):
        self.r.evidence.side_effect=OSError('evidence denied')
        with self.assertRaises(OSError):self.pair()
        self.r.action.assert_not_called()
    def test_send_unknown_or_not_sent_is_consumed_and_not_reused(self):
        for exc in (RuntimeError('unknown'),TapNotSent('before down')):
            with self.subTest(exc=exc):
                self.record['messages']=[];self.events=[dict(kind='action',action=ack.OPEN_ACTION,stage=self.key)];self.write_events()
                self.r.action.reset_mock();self.r.action.side_effect=exc
                with self.assertRaises(type(exc)):self.pair()
                self.pair();self.r.action.assert_called_once()
                self.assertIn(self.record['messages'][0]['status'],('unknown','not_sent'));self.unchanged()
    def test_new_start_never_adopts_prior_ack_run(self):
        self.r.run_id='different-run';self.pair();self.r.action.assert_not_called();self.unchanged()
    def test_maintenance_seed_needs_explicit_hash_bound_source(self):
        self.r.s['story_open_acknowledgements']={};self.r.frame=self.fresh()
        seed=dict(user_instruction='explicit policy correction',key=self.key,run_id=self.r.run_id,original_dispatch_id=self.original_dispatch['id'],state_sha256='original-state',events_sha256=hashlib.sha256((self.root/'events.jsonl').read_bytes()).hexdigest())
        proof=dict(state_sha256='original-state',user_authorization='explicit maintenance')
        for name in ('user_instruction','original_dispatch_id','events_sha256','state_sha256','run_id'):
            changed=dict(seed);changed[name]=''
            with self.assertRaises(ValueError):ack.seed_original_open(self.r,changed,proof)
        record=ack.seed_original_open(self.r,seed,proof);self.assertEqual(record['maintenance_seed'],seed)
        with self.assertRaises(ValueError):ack.seed_original_open(self.r,seed,proof)
        self.r.action.assert_not_called();self.unchanged()

if __name__=='__main__':unittest.main()
