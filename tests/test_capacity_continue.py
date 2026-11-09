"""Explicit capacity Continue and map revalidation, fake transport only."""
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import entry_preflight as flow
import runner
from assistant_worker import Control, StopRun, mainline_run
from pc_backend import FrameExpired, InputDeliveryError
from task_blockers import TaskAttention
from test_entry_preflight import configured, team
import test_entry_preflight as preflight_helpers
from test_map_layout import frame, map_frame

BINDING=dict(client='mumu',serial='bound',package='game',game_pid='pid')


def support():
    return frame([('准备战斗',148,42),('选择辅助英雄',500,125),
                  ('选择队伍',1357,831),('内讧',1190,171)])


class CapacityContinueTests(unittest.TestCase):
    def setUp(self):
        # Independent fake frames need strictly ordered times even on Windows
        # hosts whose wall clock returns identical values in a tight test loop.
        clock=[time.time()]
        def tick():
            clock[0]+=.001;return clock[0]
        timer=patch('entry_preflight.time.time',side_effect=tick)
        timer.start();self.addCleanup(timer.stop)
        self.binding=patch.object(flow,'live_binding',side_effect=lambda *args:copy.deepcopy(BINDING))
        self.binding.start();self.addCleanup(self.binding.stop)
        self.evidence=patch.object(flow,'evidence',return_value=dict(image='independent.png'))
        self.evidence.start();self.addCleanup(self.evidence.stop)

    def current(self,subject='英雄'):
        r,o,d=configured();r.run_id='old-run';r.s['active']=copy.deepcopy(o)
        r.frame=preflight_helpers.RefusalTests().modal()
        for word in r.frame.words:word['text']=word['text'].replace('英雄',subject)
        r.frame.text='\n'.join(w['text'] for w in r.frame.words);r.frame.clean=runner.norm(r.frame.text)
        flow.observe(r,r.frame,'capacity_stop')
        return r,o,d,next(iter(r.s['entry_preflight_flows'].values()))

    def receipt(self,r,command='continue-1',code='hero'):
        return dict(run_id=r.run_id,action='run',command_id=command,
                    attention_code=code,resumed_at=time.time())

    def resume(self,r,command='continue-1'):
        receipt=self.receipt(r,command)
        self.assertTrue(flow.acknowledge_capacity_continue(r,'hero',receipt))
        return receipt

    def apply(self,r,scene,f=None):
        if f is not None:r.frame=f
        return flow.step(r,r.frame,scene)

    def linked(self):
        r,o,d,rec=self.current();self.resume(r)
        self.apply(r,'map',map_frame());r.action.reset_mock();team(r)
        return r,o,d,rec

    def test_same_run_continue_returns_team_support_map_and_enters_once(self):
        r,o,d,rec=self.current();before=copy.deepcopy(r.s)
        self.resume(r);run_id=r.run_id
        self.apply(r,'team',team(r));r.back.assert_called_once();r.action.assert_not_called()
        self.assertEqual(rec['navigation'][-1]['input'],'native_back')
        r.back.reset_mock();self.apply(r,'support',support());r.back.assert_called_once()
        self.assertEqual(rec['navigation_observations'][0]['scene'],'support')
        self.apply(r,'map',map_frame())
        self.assertEqual(rec['navigation_observations'][-1]['scene'],'map')
        self.assertEqual(rec['continuation_run_id'],run_id)
        self.assertTrue(flow.map_link_ready(rec,run_id));r.action.reset_mock()
        team(r);saves=[]
        r.save.side_effect=lambda:saves.append(copy.deepcopy(rec))
        self.apply(r,'team')
        self.assertEqual(r.run_id,run_id);r.action.assert_called_once()
        self.assertEqual(rec['phase'],'submitted');self.assertEqual(len(rec['sends']),1)
        request=rec['continue_requests'][0]
        self.assertEqual(request['consumed_by'],rec['sends'][0]['id'])
        self.assertEqual(saves[0]['sends'][0]['status'],'reserved')
        self.assertEqual(saves[0]['continue_requests'][0]['consumed_by'],rec['sends'][0]['id'])
        for key in ('attempted','completed','entry_dispatches'):
            self.assertEqual(r.s[key],before[key])
        self.assertEqual(len(rec['refusals']),1);self.assertNotIn('unresolved_entries',r.s)
        r.action.reset_mock();r.back.reset_mock();self.apply(r,'team')
        r.action.assert_not_called();r.back.assert_not_called()

    def test_equipment_artifact_and_hero_capacity_share_same_run_continue(self):
        for subject,code in [('英雄','hero'),('装备','equipment'),('神器','artifact')]:
            r,o,d,rec=self.current(subject)
            self.assertEqual(rec['refusals'][-1]['proof']['subject'],subject)
            self.assertTrue(flow.acknowledge_capacity_continue(r,code,self.receipt(r,code=code)))
            self.apply(r,'team',team(r));r.back.assert_called_once();r.action.assert_not_called()
            self.assertEqual(r.run_id,'old-run');self.assertFalse(rec['sends'])

    def test_stale_map_frame_never_refreshes_or_creates_a_map_link(self):
        r,o,d,rec=self.current();self.resume(r);f=map_frame();f.at=time.time()-6
        self.apply(r,'map',f)
        self.assertIsNone(rec['map_ticket']);r.map_ticket.assert_not_called()
        self.assertFalse(rec['navigation']);r.action.assert_not_called();r.back.assert_not_called()

    def test_no_actual_continue_never_authorizes_same_run_navigation_or_entry(self):
        r,o,d,rec=self.current()
        for mode,f in [('map',map_frame()),('team',team(r)),('support',support())]:
            self.apply(r,mode,f)
        r.action.assert_not_called();r.back.assert_not_called()
        self.assertNotIn('continue_requests',rec)
        self.assertNotIn('本run',r.s['reason']);self.assertIn('不需要重新开始',r.s['reason'])

    def test_control_receipt_is_durable_idempotent_and_bound_to_refusal(self):
        r,o,d,rec=self.current();receipt=self.resume(r)
        r.save.reset_mock();self.assertTrue(flow.acknowledge_capacity_continue(r,'hero',receipt))
        r.save.assert_not_called();self.assertEqual(len(rec['continue_requests']),1)
        self.assertEqual(rec['continue_requests'][0]['refusal_sha256'],flow.state_digest(rec['refusals'][0]))
        r.action.assert_not_called();r.back.assert_not_called()

    def test_wrong_run_missing_old_future_or_wrong_reason_receipt_cannot_resume(self):
        for kind in ('run','missing','old','future','action','reason','id'):
            r,o,d,rec=self.current();receipt=self.receipt(r)
            if kind=='run':receipt['run_id']='other'
            elif kind=='missing':receipt=None
            elif kind=='old':receipt['resumed_at']=rec['refusals'][-1]['at']-1
            elif kind=='future':receipt['resumed_at']=time.time()+100
            elif kind=='action':receipt['action']='pause'
            elif kind=='reason':receipt['attention_code']='dialog'
            else:receipt['command_id']=''
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                flow.acknowledge_capacity_continue(r,'hero',receipt)
            self.assertNotIn('continue_requests',rec);r.action.assert_not_called();r.back.assert_not_called()

    def test_unrelated_attention_and_capacity_without_refusal_grant_no_authority(self):
        r,o,d,rec=self.current()
        self.assertFalse(flow.acknowledge_capacity_continue(r,'dialog',self.receipt(r)))
        self.assertFalse(flow.acknowledge_capacity_continue(r,'equipment',self.receipt(r,code='equipment')))
        rec['phase']='submitted'
        self.assertFalse(flow.acknowledge_capacity_continue(r,'hero',self.receipt(r)))
        self.assertNotIn('continue_requests',rec)
        r,o,d=configured();self.assertFalse(flow.acknowledge_capacity_continue(r,'hero',self.receipt(r)))

    def test_continue_write_failure_prevents_all_game_input(self):
        r,o,d,rec=self.current();r.save.side_effect=OSError('disk full')
        with self.assertRaises(OSError):self.resume(r)
        r.action.assert_not_called();r.back.assert_not_called();self.assertFalse(rec['sends'])

    def test_still_visible_same_capacity_modal_is_idempotent_not_a_new_permission(self):
        r,o,d,rec=self.current();self.resume(r)
        flow.observe(r,r.frame,'capacity_stop')
        self.assertEqual(len(rec['refusals']),1);self.assertEqual(len(r.s['entry_preflight_flows']),1)
        self.assertEqual(len(rec['continue_requests']),1);r.action.assert_not_called();r.back.assert_not_called()
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-capacity-repeat-test')):
            with self.assertRaises(TaskAttention):r.step(r.frame)
        self.assertEqual(len(rec['refusals']),1)

    def test_a_second_real_refusal_needs_a_new_continue_not_a_new_run(self):
        r,o,d,rec=self.linked();self.apply(r,'team');r.action.reset_mock()
        r.frame=preflight_helpers.RefusalTests().modal();flow.observe(r,r.frame,'capacity_stop')
        self.assertEqual(len(rec['refusals']),2);self.assertEqual(rec['phase'],'rejected')
        self.apply(r,'map',map_frame());r.action.assert_not_called()
        with self.assertRaises(ValueError):self.resume(r,'continue-1')
        self.resume(r,'continue-2');self.apply(r,'map',map_frame());r.action.assert_called_once()
        r.action.reset_mock();self.apply(r,'team',team(r));r.action.assert_called_once()
        self.assertEqual(len(rec['sends']),2)
        self.assertEqual(len(r.s['entry_dispatches'][o['key']]),1)
        self.assertEqual(r.run_id,'old-run');self.assertFalse(r.s['completed'])

    def test_accepted_original_response_or_real_battle_flags_never_reenter(self):
        for accepted in ('source','battle_seen','story_seen','victory_seen','settlement_observed','playback_observed_at'):
            r,o,d,rec=self.current();self.resume(r)
            if accepted=='source':r.s.setdefault('entry_acceptances',{})[rec['refusals'][-1]['source']['id']]={'mode':'battle'}
            else:r.s['active'][accepted]=True
            self.assertIsNone(self.apply(r,'team',team(r)))
            r.action.assert_not_called();r.back.assert_not_called();self.assertFalse(rec['sends'])

    def test_observed_original_battle_acceptance_retires_rejected_flow(self):
        r,o,d,rec=self.current()
        with patch('battle_auto_control.hud',return_value=True):flow.observe(r,r.frame,'battle')
        self.assertEqual(rec['phase'],'accepted')
        self.assertIsNone(self.apply(r,'team',team(r)));r.action.assert_not_called();r.back.assert_not_called()

    def test_unknown_or_not_sent_entry_is_consumed_even_after_continue_again(self):
        for error in (InputDeliveryError('unknown'),FrameExpired('expired before send')):
            r,o,d,rec=self.linked();r.action.side_effect=error
            if isinstance(error,InputDeliveryError):
                with self.assertRaises(InputDeliveryError):self.apply(r,'team')
            else:self.apply(r,'team')
            request=rec['continue_requests'][0];self.assertTrue(request['consumed_by'])
            self.assertFalse(flow.acknowledge_capacity_continue(r,'hero',self.receipt(r,'continue-again')))
            r.action.reset_mock();r.back.reset_mock();self.apply(r,'team')
            r.action.assert_not_called();r.back.assert_not_called();self.assertEqual(len(rec['sends']),1)

    def test_changed_source_or_defeat_rejects_continue(self):
        for kind in ('source','defeat','accepted'):
            r,o,d,rec=self.current()
            if kind=='source':rec['original_sha256']='changed'
            elif kind=='defeat':r.s['stage_outcomes']=[dict(stage=o['key'],outcome='defeat')]
            else:r.s['entry_acceptances']={rec['refusals'][-1]['source']['id']:{'mode':'battle'}}
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.resume(r)
            r.action.assert_not_called();r.back.assert_not_called()

    def test_changed_refusal_after_continue_is_not_an_authority(self):
        r,o,d,rec=self.current();self.resume(r);rec['refusals'][-1]['evidence']['image']='changed.png'
        self.apply(r,'team',team(r));r.action.assert_not_called();r.back.assert_not_called()

    def test_original_new_run_path_also_returns_instead_of_waiting_in_team(self):
        r,o,d,rec=self.current();r.run_id='explicit-new-run';r.s['active']=None
        self.apply(r,'team',team(r));r.back.assert_called_once();r.action.assert_not_called()
        self.assertNotIn('continue_requests',rec)

    def test_stale_missing_wrong_run_or_phase_map_link_returns_without_entry(self):
        for kind in ('stale','missing','wrong_run','phase','future','missing_time'):
            r,o,d,rec=self.linked();original=copy.deepcopy(rec['map_ticket'])
            if kind=='stale':rec['map_ticket']['verified_epoch']=time.time()-121
            elif kind=='missing':rec['map_ticket']=None
            elif kind=='wrong_run':rec['continuation_run_id']='foreign'
            elif kind=='phase':rec['map_ticket']['phase']='unverified'
            elif kind=='future':rec['map_ticket']['verified_epoch']=time.time()+10
            else:rec['map_ticket'].pop('verified_epoch')
            self.apply(r,'team');r.back.assert_called_once();r.action.assert_not_called()
            self.assertIsNone(rec['map_ticket']);self.assertIsNone(r.ticket)
            self.assertFalse(rec['sends'])
            if kind!='missing':self.assertEqual(rec['map_link_archives'][0]['ticket']['key'],original['key'])

    def test_weak_partial_or_covered_preparation_never_sends_return(self):
        for kind in ('team_partial','support_weak','support_duplicate','support_missing','modal','tutorial','paid'):
            r,o,d,rec=self.current();self.resume(r);f=team(r) if kind.startswith('team') or kind in ('modal','tutorial','paid') else support()
            mode='team' if f is r.frame else 'support'
            if kind=='team_partial':f.words=[w for w in f.words if w['text']!='管理队伍']
            elif kind=='support_weak':f.find('选择队伍')['score']=.979
            elif kind=='support_duplicate':f.words.append(copy.deepcopy(f.find('选择队伍')))
            elif kind=='support_missing':f.words=[w for w in f.words if w['text']!='准备战斗']
            elif kind=='modal':f.words.extend(frame([('确认',800,500),('取消',600,500)]).words)
            elif kind=='tutorial':f.words.extend(frame([('跳过教学',1450,42)]).words)
            else:f.words.extend(frame([('购买体力',800,500)]).words)
            self.apply(r,mode,f);r.action.assert_not_called();r.back.assert_not_called()

    def test_stale_frame_or_target_geometry_changes_never_sends_return(self):
        for kind in ('stale','binding','geometry'):
            r,o,d,rec=self.current();self.resume(r);f=team(r)
            if kind=='stale':f.at=time.time()-6;self.apply(r,'team')
            else:
                if kind=='binding':rec['binding']['game_pid']='new-process'
                else:rec['raw_size']=[1280,720]
                with self.assertRaises(ValueError):self.apply(r,'team')
            r.action.assert_not_called();r.back.assert_not_called()

    def test_native_return_intent_and_evidence_must_be_saved_before_back(self):
        r,o,d,rec=self.current();self.resume(r);team(r);order=[]
        r.save.side_effect=lambda:order.append(('save',copy.deepcopy(rec['navigation'])))
        r.back.side_effect=lambda *a:order.append(('back',copy.deepcopy(rec['navigation'])))
        self.apply(r,'team')
        self.assertEqual([v[0] for v in order],['save','back','save'])
        self.assertEqual(order[0][1][-1]['status'],'reserved')
        self.assertEqual(order[1][1][-1]['status'],'reserved')
        self.assertEqual(order[-1][1][-1]['status'],'sent')
        self.assertFalse(rec['sends'])

    def test_return_evidence_or_intent_write_failure_sends_nothing(self):
        for kind in ('evidence','save'):
            r,o,d,rec=self.current();self.resume(r);team(r)
            if kind=='save':r.save.side_effect=OSError('disk')
            with patch.object(flow,'evidence',side_effect=OSError('evidence') if kind=='evidence' else None,
                              return_value=dict(image='saved.png')):
                with self.assertRaises(OSError):self.apply(r,'team')
            r.back.assert_not_called();r.action.assert_not_called();self.assertFalse(rec['sends'])

    def test_unknown_native_return_is_not_replayed_or_promoted_to_resource_entry(self):
        r,o,d,rec=self.current();self.resume(r);team(r);r.back.side_effect=InputDeliveryError('unknown')
        with self.assertRaises(InputDeliveryError):self.apply(r,'team')
        self.assertEqual(rec['navigation'][-1]['status'],'unknown');r.back.reset_mock()
        for mode,f in [('team',team(r)),('support',support()),('map',map_frame())]:self.apply(r,mode,f)
        r.action.assert_not_called();r.back.assert_not_called();self.assertFalse(rec['sends'])

    def test_unchanged_team_page_has_bounded_back_sends_not_rapid_repeats(self):
        r,o,d,rec=self.current();self.resume(r);team(r);self.apply(r,'team');r.back.reset_mock()
        self.apply(r,'team');r.back.assert_not_called()
        for _ in range(2):
            team(r);now=rec['navigation'][-1]['finished_at']+5;r.frame.at=now
            with patch('entry_preflight.time.time',return_value=now+.01):self.apply(r,'team')
        self.assertEqual(r.back.call_count,1);self.assertEqual(len(rec['navigation']),2)
        self.assertFalse(rec['sends'])

    def test_capacity_modal_preempts_return_and_allows_another_explicit_continue(self):
        r,o,d,rec=self.current();self.resume(r);f=preflight_helpers.RefusalTests().modal()
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-capacity-resume-test')):
            with self.assertRaises(TaskAttention) as caught:r.step(f)
        self.assertEqual(caught.exception.code,'hero');r.action.assert_not_called();r.back.assert_not_called()
        self.resume(r,'continue-2');self.apply(r,'team',team(r));r.back.assert_called_once()

    def test_runner_real_step_uses_recovery_before_default_team_gate(self):
        r,o,d,rec=self.current();r.observe_progress_evidence=runner.Runner.observe_progress_evidence.__get__(r)
        before=copy.deepcopy(r.s['attempted'])
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-capacity-step-test')):
            with self.assertRaises(TaskAttention):r.step(r.frame)
            self.resume(r);r.step(team(r))
        r.back.assert_called_once();r.action.assert_not_called();self.assertFalse(rec['sends'])
        self.assertEqual(r.s['attempted'],before);self.assertFalse(r.s['completed'])


class ContinueControlTests(unittest.TestCase):
    def control(self,folder):
        return Control(dict(run_dir=folder,run_id='run',settings={'task':'mainline'},target={'client':'mumu'}))

    def test_attention_returns_only_new_matching_user_run_command(self):
        old=dict(run_id='run',action='run',command_id='old')
        new=dict(run_id='run',action='run',command_id='new')
        with tempfile.TemporaryDirectory() as folder:
            control=self.control(folder)
            with patch('assistant_worker.read_json',side_effect=[old,old,new]),patch.object(control,'status'),patch('assistant_worker.time.sleep'):
                receipt=control.attention(TaskAttention('hero','容量已满','手动处理后继续'))
        self.assertEqual(receipt['run_id'],'run');self.assertEqual(receipt['command_id'],'new')
        self.assertEqual(receipt['attention_code'],'hero');self.assertEqual(receipt['action'],'run')

    def test_attention_cannot_turn_stop_or_foreign_command_into_continue(self):
        for command in (dict(run_id='run',action='stop',command_id='new'),
                        dict(run_id='other',action='run',command_id='new')):
            with tempfile.TemporaryDirectory() as folder:
                control=self.control(folder)
                with patch('assistant_worker.read_json',side_effect=[{},command]),patch.object(control,'status'):
                    with self.assertRaises(StopRun):control.attention(TaskAttention('hero','容量已满','继续'))

    def test_mainline_worker_passes_attention_receipt_to_capacity_journal(self):
        instances=[];receipt=dict(run_id='same-run',action='run',command_id='new',attention_code='hero',resumed_at=time.time())
        class FakeRunner:
            def __init__(self,**kw):
                self.pc=None;self.cfg={};self.s={'completed':{},'attempted':{},'active':None};self.ticket=None
                self.mode_since=0;self.input_sequence=0;self.calls=0;instances.append(self)
            def start_current_screen(self):pass
            def capture(self):return SimpleNamespace(image=runner.np.zeros((900,1600,3),runner.np.uint8))
            def save(self):pass
            def step(self,f):
                self.calls+=1
                if self.calls==1:raise TaskAttention('hero','容量满','处理后继续')
                return False,0
        with tempfile.TemporaryDirectory() as folder:
            request=dict(run_id='same-run',run_dir=folder,settings=dict(observe=False,task='mainline',mumu={}),
                         target=dict(client='mumu',serial='bound',package='game'))
            ctl=Mock();ctl.attention.return_value=receipt
            story=SimpleNamespace(total_wins=lambda:0,context=False,stage_label=lambda:'')
            with patch('assistant_worker.validate_run',return_value=(Path(folder),{})),patch.object(runner,'ROOT',Path(folder)), \
                 patch('runner.Runner',FakeRunner),patch('runner.classify',return_value='unknown'), \
                 patch('story_core.StoryController',return_value=story), \
                 patch('assistant_worker.ScreenStabilityGate',return_value=Mock(waiting=Mock(return_value=False))), \
                 patch('entry_preflight.acknowledge_capacity_continue') as acknowledge:
                mainline_run(request,ctl)
            acknowledge.assert_called_once_with(instances[0],'hero',receipt)
            self.assertEqual(instances[0].run_id,'same-run');self.assertEqual(instances[0].calls,2)


if __name__=='__main__':unittest.main()
