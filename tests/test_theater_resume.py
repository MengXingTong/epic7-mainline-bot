"""Offline guards for explicit same-run Theater maintenance; no real processes/input."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_config import load_theater_resume_request
from theater_core import classify
import test_theater as h


class DialogueReviveTests(unittest.TestCase):
    def observation(self):
        return h.observation([
            h.token('死亡探究者雷伊',800,660),
            h.token('有了让死尸复活的降灵术和将另存的自我注入',800,760)
        ],visuals=['theater_story'])

    def test_full_observed_narrative_is_story_not_a_paid_revive_prompt(self):
        self.assertEqual(classify(self.observation()).scene,'theater_story')

    def test_missing_or_ambiguous_speaker_wrong_band_or_weak_ocr_stays_blocked(self):
        for mode in ('missing','ambiguous','band','weak','no_story','battle'):
            with self.subTest(mode=mode):
                obs=self.observation()
                if mode=='missing':obs.tokens.pop(0)
                elif mode=='ambiguous':obs.tokens.append(h.token('其他角色',850,650))
                elif mode=='band':obs.tokens[1]=h.token(obs.tokens[1].text,800,400)
                elif mode=='weak':obs.tokens[1]=h.token(obs.tokens[1].text,800,760,score=.8)
                elif mode=='no_story':obs.visuals.clear()
                else:obs.visuals.add('theater_battle')
                self.assertEqual(classify(obs).scene,'theater_blocked')

    def test_any_weak_modal_cost_capacity_network_or_defeat_hint_still_vetoes(self):
        for text in ('确认','取消','点击关闭','是否使用','消耗','立即复活','复活',
                     '购买门票','天空石','门票不足','连接失败','装备背包已满','战斗失败'):
            with self.subTest(text=text):
                obs=self.observation();obs.tokens.append(h.token(text,800,500,score=.2))
                self.assertIn(classify(obs).scene,('theater_blocked','theater_defeat'))

    def test_other_revive_or_purchase_dialogue_is_not_generally_whitelisted(self):
        for text in ('复活','是否消耗100天空石复活','我们的朋友也许还能复活吧',
                     '有了让死尸复活的降灵术就可以购买门票'):
            obs=self.observation();obs.tokens[1]=h.token(text,800,760)
            self.assertEqual(classify(obs).scene,'theater_blocked')


    def test_observed_surgery_line_is_dialogue_but_resource_and_speaker_guards_stay(self):
        text='可以重新手术复活他们，但每次都会缩短几周的寿命。'
        obs=self.observation();obs.tokens[1]=h.token(text,800,760)
        self.assertEqual(classify(obs).scene,'theater_story')
        for extra in ('确认','消耗','购买门票','天空石','复活','连接失败','装备背包已满','战斗失败'):
            other=copy.deepcopy(obs);other.tokens.append(h.token(extra,800,500,score=.2))
            self.assertIn(classify(other).scene,('theater_blocked','theater_defeat'))
        for mode in ('speaker','weak','position'):
            other=copy.deepcopy(obs)
            if mode=='speaker':other.tokens.pop(0)
            elif mode=='weak':other.tokens[1]=h.token(text,800,760,score=.3)
            else:other.tokens[1]=h.token(text,800,400)
            self.assertEqual(classify(other).scene,'theater_blocked')

    def test_private_surgery_failure_hash_verified_replays_as_story_only(self):
        import hashlib
        from abyss_core import Observation,Token
        audit=Path(__file__).resolve().parents[1]/'.local/theater-normal-reward-20261105'
        path=audit/'surgery-failure.json'
        if not path.is_file():self.skipTest('未分发当前手术剧情私有故障帧')
        meta=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256(path.with_suffix('.png').read_bytes()).hexdigest(),meta['image_sha256'])
        obs=Observation(meta['width'],meta['height'],[Token(**t) for t in meta['tokens']],
                        meta['captured_at'],visuals=set(meta['visuals']))
        self.assertEqual(classify(obs).scene,'theater_story')


class SameRunReloadPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)/'home';self.profile=Path(self.temp.name)/'profile'
        self.run='a'*32;self.folder=self.home/'runs'/self.run
        self.folder.mkdir(parents=True);(self.profile/'theater').mkdir(parents=True)
        self.request=dict(run_id=self.run,run_dir=str(self.folder),home=str(self.home),
            settings=dict(task='theater',observe=False,pc_input='messages',data_dir=str(self.profile)),
            target=dict(client='pc',hwnd=1,pid=2,created=3,exe='EpicSeven.exe',title='game'))
        self.put(self.folder/'request.json',self.request)
        self.put(self.home/'active-run.json',dict(run_id=self.run,run_dir=str(self.folder),worker_pid=44))
        self.put(self.folder/'status.json',dict(run_id=self.run,mode='stopped'))
        self.put(self.folder/'control.json',dict(run_id=self.run,action='stop',command_id='stop'))
        self.put(self.profile/'state.json',dict(attempted={},completed={}))
        self.state=dict(active=dict(run_id=self.run,key='episode',phase='story'),
                        actions=[dict(run_id=self.run,kind='guide',status='sent')])
        self.put(self.profile/'theater/state.json',self.state)
        self.alive=patch('assistant_config.process_is_alive',return_value=False).start()
        self.addCleanup(patch.stopall)

    def put(self,path,value):path.write_text(json.dumps(value),encoding='utf-8')
    def load(self):return load_theater_resume_request(self.run,self.home)
    def snapshot(self):return {str(p):p.read_bytes() for p in Path(self.temp.name).rglob('*') if p.is_file()}

    def pending_ticket_state(self):
        from entry_journal import attempt_digest
        from theater_core import Episode
        ep=Episode('测试剧目',8,2)
        attempt=dict(key=ep.key,**vars(ep),run_id=self.run,evidence='evidence/open.png',at=1)
        opened=dict(id='open',kind='open',status='sent',run_id=self.run,key=ep.key,episode=ep.key,
                    entry=copy.deepcopy(attempt),original_sha256=attempt_digest(attempt),evidence=attempt['evidence'])
        return dict(schema=1,registration_id='existing',active=dict(attempt,phase='await_ticket',steps={}),
                    attempted={ep.key:attempt},completed={},entry_dispatches={ep.key:[copy.deepcopy(opened)]},
                    actions=[opened],unresolved_entries=[],last_cleared=None)

    def test_same_run_original_sent_open_can_reload_before_its_first_ticket_without_mutation(self):
        state=self.pending_ticket_state();self.put(self.profile/'theater/state.json',state)
        before=self.snapshot();self.assertEqual(self.load(),self.request);self.assertEqual(before,self.snapshot())

    def test_pending_ticket_reload_never_borrows_archive_or_resends_unknown_paid_entry(self):
        original=self.pending_ticket_state();key=original['active']['key']
        for mode in ('ticket','guide','unknown','not_sent','foreign','grant','archive','completed',
                     'missing_attempt','changed_dispatch','schema','last_action'):
            with self.subTest(mode=mode):
                s=copy.deepcopy(original)
                if mode in ('ticket','guide'):s['actions'].append(dict(s['actions'][0],kind=mode))
                elif mode in ('unknown','not_sent'):s['actions'][0]['status']=mode
                elif mode=='foreign':s['active']['run_id']='old'
                elif mode=='grant':s['active']['confirmation_continuation_id']='old-permission'
                elif mode=='archive':s['unresolved_entries'].append(dict(entry=copy.deepcopy(s['active'])))
                elif mode=='completed':s['completed'][key]={}
                elif mode=='missing_attempt':s['attempted'].clear()
                elif mode=='changed_dispatch':s['entry_dispatches'][key][0]['original_sha256']='changed'
                elif mode=='schema':del s['schema']
                else:s['actions'].append(dict(run_id=self.run,kind='advance',status='sent',key='other'))
                self.put(self.profile/'theater/state.json',s);before=self.snapshot()
                with self.assertRaises(ValueError):self.load()
                self.assertEqual(before,self.snapshot())

    def test_exact_stopped_run_is_read_only_and_preserves_original_request_and_state(self):
        before=self.snapshot();self.assertEqual(self.load(),self.request);self.assertEqual(self.snapshot(),before)

    def test_alive_or_unqueryable_old_worker_never_allows_a_second_writer(self):
        for result in (True,OSError('access denied')):
            with self.subTest(result=str(result)):
                if isinstance(result,Exception):self.alive.side_effect=result
                else:self.alive.return_value=result
                before=self.snapshot()
                with self.assertRaises((ValueError,OSError)):self.load()
                self.assertEqual(self.snapshot(),before)

    def test_attention_nonstop_foreign_missing_or_replaced_metadata_is_not_a_reload(self):
        changes=[('status.json',dict(run_id=self.run,mode='attention')),
                 ('status.json',dict(run_id='other',mode='stopped')),
                 ('control.json',dict(run_id=self.run,action='run')),
                 ('request.json',dict(self.request,run_id='other'))]
        for name,value in changes:
            with self.subTest(name=name,value=value):
                path=self.folder/name;old=path.read_bytes();self.put(path,value)
                with self.assertRaises(ValueError):self.load()
                path.write_bytes(old)
        old=(self.folder/'request.json').read_bytes();(self.folder/'request.json').unlink()
        with self.assertRaises(ValueError):self.load()
        (self.folder/'request.json').write_bytes(old)

    def test_stop_marker_is_never_archived_or_deleted(self):
        (self.profile/'STOP').write_text('new stop',encoding='utf-8');before=self.snapshot()
        with self.assertRaises(ValueError):self.load()
        self.assertEqual(self.snapshot(),before)

    def test_unresolved_dispatch_missing_active_wrong_run_and_wrong_phase_reject(self):
        for mode in ('reserved','unknown','missing','foreign','opening'):
            with self.subTest(mode=mode):
                state=copy.deepcopy(self.state)
                if mode in ('reserved','unknown'):state['actions'][0]['status']=mode
                elif mode=='missing':state['active']=None
                elif mode=='foreign':state['active']['run_id']='other'
                else:state['active']['phase']='opening'
                self.put(self.profile/'theater/state.json',state);before=self.snapshot()
                with self.assertRaises(ValueError):self.load()
                self.assertEqual(self.snapshot(),before)

    def test_other_task_or_client_and_missing_original_profile_are_rejected(self):
        for change in ('task','client','observe','profile'):
            request=copy.deepcopy(self.request)
            if change=='task':request['settings']['task']='mainline'
            elif change=='client':request['target']['client']='mumu'
            elif change=='observe':request['settings']['observe']=True
            else:request['settings']['data_dir']=str(self.profile/'missing')
            self.put(self.folder/'request.json',request)
            with self.assertRaises(ValueError):self.load()

    def test_path_traversal_and_no_implicit_current_run_are_rejected(self):
        for run in ('../profile',None,'','A'*32,'a'*31):
            with self.assertRaises(ValueError):load_theater_resume_request(run,self.home)


    def untouched_state(self):
        return dict(schema=1,registration_id='profile',active=None,
                    attempted={'old':dict(run_id='old')},completed={},
                    entry_dispatches={'old':[dict(entry=dict(run_id='old'),status='unknown')]},
                    unresolved_entries=[dict(entry=dict(run_id='old',phase='story'))],
                    actions=[dict(run_id='old',kind='open',status='unknown')])

    def test_untouched_current_run_can_reload_without_changing_old_archives(self):
        self.put(self.profile/'theater/state.json',self.untouched_state())
        before=self.snapshot();self.assertEqual(self.load(),self.request)
        self.assertEqual(self.snapshot(),before)

    def test_missing_active_with_any_owned_history_is_not_an_untouched_reload(self):
        for field in ('attempted','completed','entry_dispatches','unresolved_entries','actions'):
            with self.subTest(field=field):
                state=self.untouched_state()
                if isinstance(state[field],dict):state[field]['own']={'nested':{'run_id':self.run}}
                else:state[field].append({'nested':{'run_id':self.run}})
                self.put(self.profile/'theater/state.json',state);before=self.snapshot()
                with self.assertRaises(ValueError):self.load()
                self.assertEqual(self.snapshot(),before)

    def test_untouched_reload_still_rejects_stop_and_missing_schema(self):
        state=self.untouched_state();self.put(self.profile/'theater/state.json',state)
        stop=self.profile/'STOP';stop.write_text('stop',encoding='utf-8');before=self.snapshot()
        with self.assertRaises(ValueError):self.load()
        self.assertEqual(self.snapshot(),before);stop.unlink()
        del state['schema'];self.put(self.profile/'theater/state.json',state);before=self.snapshot()
        with self.assertRaises(ValueError):self.load()
        self.assertEqual(self.snapshot(),before)


    def test_standalone_free_close_only_reload_keeps_all_archives_and_actions(self):
        state=self.untouched_state()
        state['actions'].append(dict(run_id=self.run,kind='close_reward_notice',status='sent',
                                     key=None,episode=None,evidence='notice.png'))
        self.put(self.profile/'theater/state.json',state);before=self.snapshot()
        self.assertEqual(self.load(),self.request);self.assertEqual(self.snapshot(),before)
        for change in ('unknown','reserved','duplicate','entry','key','no_evidence'):
            bad=copy.deepcopy(state);a=bad['actions'][-1]
            if change in ('unknown','reserved'):a['status']=change
            elif change=='duplicate':bad['actions'].append(copy.deepcopy(a))
            elif change=='entry':a['kind']='open'
            elif change=='key':a['key']='old-entry'
            else:del a['evidence']
            self.put(self.profile/'theater/state.json',bad);before=self.snapshot()
            with self.assertRaises(ValueError):self.load()
            self.assertEqual(self.snapshot(),before)
