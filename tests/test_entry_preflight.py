"""Pure fake transport: explicit preflight rejection, never generic paid retry."""
import copy,time,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import entry_preflight as flow
from entry_journal import reserve_entry,finish_dispatch,attempt_digest
from story_reopen import state_digest
from test_map_layout import frame,map_frame,fake_runner
from test_team_preparation import preparation


def configured():
    r=fake_runner(map_frame());r.run_id='new-run';r.cfg.update(serial='bound',package='game')
    r.pc=None;r.adb=Mock(return_value=b'pid');r.observe_progress_evidence=Mock(return_value=(True,.25))
    r.title_matches=Mock(return_value=True)
    o=dict(key='E3-C6-S5',episode=3,chapter=6,stage=5,name='内讧',cost=20,stamina_before=100,team_entry_mode='auto_on',start_epoch=1.)
    d=reserve_entry(r.s,o['key'],o);finish_dispatch(d,'sent');r.s['active']=None
    r.s['entry_preparations']={d['id']:dict(phase='sent',run_id='old-run')}
    r.evidence=Mock(return_value='independent.png')
    r.map_ticket=Mock(return_value=(dict(o,locked=False,clear_badge=False,verified_epoch=time.time()),[dict(stage=6,locked=True)],'未通关蓝色当前节点'))
    return r,o,d


def rejected(r,o):
    source=dict(id='dispatch:original',kind='dispatch',key=o['key'],run_id='old-run',sent_at=2.)
    with patch.object(flow,'live_binding',return_value=dict(client='mumu',serial='bound',package='game',game_pid='pid')):
        return flow.create_rejection(r,source,dict(kind='complete_capacity_modal'),dict(image='saved.png'))


def apply(r,scene):
    with patch.object(flow,'live_binding',return_value=dict(client='mumu',serial='bound',package='game',game_pid='pid')),patch.object(flow,'evidence',return_value=dict(image='independent.png')):
        return flow.step(r,r.frame,scene)


def team(r):
    f=preparation();f.find('新关卡')['text']='内讧';r.frame=f;return f


def ready(r,o):
    rec=rejected(r,o);apply(r,'map');r.action.reset_mock();team(r);return rec


class RefusalTests(unittest.TestCase):
    def modal(self):
        return frame([('背包空间不足',800,275),('英雄背包已满。',800,436),('请整理或扩充英雄背包后再重试。',800,463),('取消',529,620),('整理',797,620),('扩充',1066,620)])

    def test_only_complete_current_modal_is_positive_rejection(self):
        self.assertEqual(flow.modal(self.modal())['subject'],'英雄')
        for failure in ('missing','weak','moved','unknown','mixed_subject'):
            f=self.modal()
            if failure=='missing':f.words.pop()
            elif failure=='weak':f.words[1]['score']=.979
            elif failure=='moved':f.words[0]['x']=100
            elif failure=='mixed_subject':f.words[2]['text']='请整理或扩充装备背包后再重试。'
            else:f.words+=frame([('确认',900,575)]).words
            self.assertIsNone(flow.modal(f))

    def test_rejected_old_flow_never_adopts_or_blocks_a_different_current_entry(self):
        for kind in ('active','ticket'):
            r,o,d=configured();rec=rejected(r,o)
            if kind=='active':r.s['active']=dict(key='independent-current-stage')
            else:r.ticket=dict(key='independent-current-stage')
            self.assertIsNone(apply(r,'team'));r.action.assert_not_called()
            self.assertEqual(rec['phase'],'rejected');self.assertFalse(rec['sends'])

    def test_explicit_defeat_cannot_be_undone_by_an_older_preflight_rejection(self):
        r,o,d=configured();rec=rejected(r,o)
        r.s['stage_outcomes']=[dict(stage=o['key'],outcome='defeat',evidence='actual-defeat.png')]
        with self.assertRaises(ValueError):apply(r,'map')
        r.action.assert_not_called();self.assertFalse(rec['sends'])

    def test_sent_or_unknown_response_alone_never_generates_a_recovery(self):
        r,o,d=configured();self.assertIsNone(apply(r,'map'));r.action.assert_not_called()
        self.assertNotIn('entry_preflight_flows',r.s)

    def test_current_capacity_is_persisted_before_attention_but_accepted_source_is_not_rejected(self):
        r,o,d=configured();r.run_id='old-run';r.s['active']=copy.deepcopy(o);r.frame=self.modal()
        with patch.object(flow,'evidence',return_value=dict(image='independent.png')),patch.object(flow,'live_binding',return_value=dict(client='mumu')):
            flow.observe(r,r.frame,'capacity_stop')
        self.assertEqual(len(r.s['entry_preflight_flows']),1);r.save.assert_called();r.action.assert_not_called()
        r,o,d=configured();r.run_id='old-run';r.s['active']=copy.deepcopy(o);r.frame=self.modal()
        r.s['entry_acceptances']={'dispatch:'+d['id']:dict(mode='battle')}
        with patch.object(flow,'evidence') as proof:flow.observe(r,r.frame,'capacity_stop')
        proof.assert_not_called();self.assertNotIn('entry_preflight_flows',r.s)

    def test_same_run_capacity_handling_without_continue_cannot_resend(self):
        r,o,d=configured();rec=rejected(r,o);r.run_id='old-run'
        self.assertEqual(apply(r,'map'),(True,.25));r.action.assert_not_called();self.assertFalse(rec['sends'])

    def test_current_new_run_navigation_and_entry_preserve_all_original_history(self):
        r,o,d=configured();before=copy.deepcopy(r.s);rec=rejected(r,o);order=[]
        r.save.side_effect=lambda:order.append('save')
        apply(r,'map');r.action.reset_mock();order.clear();team(r)
        r.action.side_effect=lambda *a:order.append('input')
        with patch('entry_preflight.time.time',return_value=r.frame.at+.01):apply(r,'team')
        self.assertEqual(order,['save','input','save']);self.assertEqual(rec['phase'],'submitted')
        self.assertEqual(rec['sends'][0]['status'],'sent');self.assertEqual(r.s['active']['entry_preflight_flow'],rec['id'])
        for name in ('attempted','entry_dispatches','completed'):self.assertEqual(r.s[name],before[name])
        r.action.reset_mock();self.assertEqual(apply(r,'team'),(True,.25));r.action.assert_not_called()

    def test_unknown_send_is_consumed_and_never_replayed(self):
        r,o,d=configured();rec=ready(r,o);r.action.side_effect=RuntimeError('send unknown')
        with self.assertRaises(RuntimeError):apply(r,'team')
        self.assertEqual(rec['sends'][-1]['status'],'unknown');self.assertEqual(rec['phase'],'invoking')
        r.action.reset_mock();apply(r,'team');r.action.assert_not_called()

    def test_not_sent_entry_is_not_automatically_reused(self):
        from pc_backend import TapNotSent
        r,o,d=configured();rec=ready(r,o);r.action.side_effect=TapNotSent('before down')
        apply(r,'team');self.assertEqual(rec['phase'],'unresolved');self.assertEqual(rec['sends'][-1]['status'],'not_sent')
        r.action.reset_mock();apply(r,'team');r.action.assert_not_called()

    def test_persistence_and_independent_evidence_errors_prevent_input(self):
        for failure in ('save','evidence'):
            r,o,d=configured();rec=ready(r,o)
            if failure=='save':r.save.side_effect=OSError('disk')
            with patch.object(flow,'live_binding',return_value=rec['binding']),patch.object(flow,'evidence',side_effect=OSError('disk') if failure=='evidence' else None,return_value=dict(image='saved')):
                with self.assertRaises(OSError):flow.step(r,r.frame,'team')
            r.action.assert_not_called()

    def test_wrong_binding_completed_unknown_modal_cost_or_stage_never_enters(self):
        for failure in ('binding','complete','modal','cost','target','title','map_link'):
            r,o,d=configured();rec=ready(r,o)
            if failure=='binding':rec['binding']['game_pid']='other'
            elif failure=='complete':r.s['completed'][o['key']]={}
            elif failure=='modal':r.frame.words+=frame([('跳过教学',1452,42)]).words
            elif failure=='cost':r.frame.find('20/100')['text']='21/100'
            elif failure=='target':r.frame.find('进行任务')['score']=.979
            elif failure=='title':r.title_matches.return_value=False
            else:rec['continuation_run_id']='foreign'
            if failure=='binding':
                with self.assertRaises(ValueError):apply(r,'team')
            else:apply(r,'team')
            r.action.assert_not_called();self.assertFalse(rec['sends'])

    def test_true_battle_acceptance_is_independent_and_prevents_capacity_recovery(self):
        r,o,d=configured();rec=ready(r,o);apply(r,'team');r.action.reset_mock()
        with patch.object(flow,'evidence',return_value=dict(image='battle.png')),patch('battle_auto_control.hud',return_value=True):
            flow.observe(r,r.frame,'battle')
        self.assertEqual(rec['phase'],'accepted');self.assertTrue(r.s['entry_acceptances'])
        self.assertIsNone(apply(r,'team'));r.action.assert_not_called()
        with patch.object(flow,'evidence') as e:flow.observe(r,self.modal(),'capacity_stop')
        e.assert_not_called();self.assertEqual(len(rec['refusals']),1)

    def test_refusal_of_continuation_requires_new_independent_response_for_legacy_new_run(self):
        r,o,d=configured();rec=ready(r,o);apply(r,'team');r.action.reset_mock();r.frame=self.modal()
        with patch.object(flow,'evidence',return_value=dict(image='new-refusal.png')):flow.observe(r,r.frame,'capacity_stop')
        self.assertEqual(len(rec['refusals']),2);self.assertEqual(rec['phase'],'rejected')
        r.frame=map_frame();apply(r,'map');r.action.assert_not_called()
        r.run_id='newer-run';r.s['active']=None;apply(r,'map');r.action.assert_called_once()
        self.assertEqual(len(r.s['entry_dispatches'][o['key']]),1)

    def test_free_auto_context_is_not_result_or_entry_authority(self):
        r,o,d=configured();rec=ready(r,o);apply(r,'team')
        self.assertEqual(flow.active_context(r)['scope'],'verified_preflight_continuation')
        self.assertFalse(r.s['completed']);self.assertEqual(len(r.s['entry_dispatches'][o['key']]),1)
        rec['sends'][-1]['status']='unknown';self.assertIsNone(flow.active_context(r))

    def test_import_is_never_automatic_and_requires_matching_immutable_files(self):
        r,o,d=configured();h=dict(id='old',key=o['key'],status='sent',run_id='old-run',sent_at=2.)
        r.s['tutorial_entry_handoffs']=[h]
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'review.txt';path.write_text('Actual reviewed tool observation; missing original pixels disclosed.')
            import hashlib
            source=dict(id='handoff:old',kind='tutorial_handoff',key=o['key'],run_id='old-run',sent_at=2.,source_sha256=state_digest(h))
            permit=dict(id='review',key=o['key'],user_instruction='Fix this proven pre-entry refusal only',source_hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest()},state_sha256=state_digest(r.s),original_sha256=attempt_digest(o),source=source,binding=dict(client='mumu'))
            with patch.object(flow,'live_binding',return_value=dict(client='mumu')):
                bad=copy.deepcopy(permit);bad['user_instruction']=''
                with self.assertRaises(ValueError):flow.import_reviewed_rejection(r,bad)
                self.assertNotIn('entry_preflight_flows',r.s)
                rec=flow.import_reviewed_rejection(r,permit)
            self.assertEqual(rec['phase'],'rejected');self.assertFalse(rec['refusals'][0]['proof']['original_popup_pixels_retained'])

if __name__=='__main__':unittest.main()
