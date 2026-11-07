"""Two-row clipped results require current check + original same-run playback chain."""
import copy,datetime,hashlib,json,os,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import runner
from entry_journal import attempt_digest
from mainline_story_results import recorded_clipped_story_completion
from task_blockers import TaskAttention
from test_era_map import era_map
from test_story_only_nodes import fake_runner

class RecordedClippedStoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'evidence').mkdir()
        for name in ('preflight','playback','accepted'):(self.root/'evidence'/f'{name}.png').write_bytes(name.encode())
        self.f=era_map();self.f.words.pop(4)
        self.d,self.rows,_=runner.Runner.__new__(runner.Runner).map_ticket(self.f)
        self.rows[1]['locked']=True
        self.start=datetime.datetime(2026,11,6,20,tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        self.o=dict(key='E6-C1-S1',episode=6,chapter=1,stage=1,name='original',cost=0,entry_kind='story_only',
                    start_epoch=self.start.timestamp(),evidence='evidence/preflight.png')
        self.a=dict(self.o,playback_observed_at=(self.start+datetime.timedelta(seconds=2)).isoformat(),playback_evidence='evidence/playback.png')
        self.dispatch=dict(id='synthetic-dispatch',status='sent',entry=copy.deepcopy(self.o),original_sha256=attempt_digest(self.o))
        self.binding=dict(client='mumu',serial='fake',package='fake')
        self.ack=dict(run_id='synthetic-run',key=self.o['key'],original_dispatch_id=self.dispatch['id'],original_sha256=attempt_digest(self.o),
                      phase='accepted',accepted_scene='story',accepted_at=self.start.timestamp()+2,binding=self.binding,messages=[],
                      preflight_sha256=hashlib.sha256(b'preflight').hexdigest(),acceptance_evidence='evidence/accepted.png')
        self.s=dict(active=self.a,attempted={self.o['key']:self.o},completed={},entry_dispatches={self.o['key']:[self.dispatch]},
                    story_open_acknowledgements={self.dispatch['id']:self.ack})
        items=[('action',dict(action='观看故事（仅一次）')),('screen',dict(screen='story')),
               ('action',dict(action='跳过剧情')),('screen',dict(screen='skip_confirm')),
               ('action',dict(action='确认跳过剧情')),('screen',dict(screen='story_reward')),
               ('action',dict(action='关闭已发放的免费奖励遮罩')),('screen',dict(screen='map'))]
        self.events=[dict(kind=kind,stage=self.o['key'],time=(self.start+datetime.timedelta(seconds=i)).isoformat(),**fields) for i,(kind,fields) in enumerate(items)]
    def read(self):
        return recorded_clipped_story_completion(self.f,self.s,self.d,self.rows,self.events,run_id='synthetic-run',current_binding=self.binding,root=self.root)
    def test_full_original_playback_reward_and_current_check_is_result_only(self):
        before=copy.deepcopy(self.s);proof=self.read();self.assertIsNotNone(proof)
        self.assertFalse(proof['clickable']);self.assertIsNone(proof['star_count']);self.assertEqual(proof['stage'],1)
        self.assertEqual(self.s,before);self.assertEqual(proof['original_dispatch_id'],self.dispatch['id'])
    def test_same_grid_without_internal_check_is_never_enough(self):
        self.f=era_map(False);self.f.words.pop(4);self.assertIsNone(self.read())
    def test_wrong_run_binding_unaccepted_playback_or_resend_chain_is_rejected(self):
        for mode in ('run','binding','phase','scene','messages','hash','entry','no_play','paid','archive','completed','changed_active'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode=='run':self.ack['run_id']='other'
                elif mode=='binding':self.ack['binding']={'client':'other'}
                elif mode=='phase':self.ack['phase']='awaiting_acceptance'
                elif mode=='scene':self.ack['accepted_scene']='battle'
                elif mode=='messages':self.ack['messages']=[{'status':'sent'}]
                elif mode=='hash':self.dispatch['original_sha256']='changed'
                elif mode=='entry':self.dispatch['entry']['name']='changed'
                elif mode=='no_play':self.a.pop('playback_observed_at')
                elif mode=='paid':self.a['cost']=8
                elif mode=='archive':self.s['unresolved_entries']=[{'entry':copy.deepcopy(self.a)}]
                elif mode=='completed':self.s['completed'][self.o['key']]={}
                else:self.a['name']='changed'
                self.assertIsNone(self.read())
    def test_missing_changed_or_outside_source_evidence_is_rejected(self):
        for mode in ('missing','changed','outside'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode=='missing':(self.root/'evidence/playback.png').unlink()
                elif mode=='changed':(self.root/'evidence/preflight.png').write_bytes(b'changed')
                else:self.a['playback_evidence']='../outside.png'
                self.assertIsNone(self.read())
    def test_battle_defeat_or_extra_navigation_breaks_source_chain(self):
        for mode in ('battle','defeat','resource_stop','capacity_stop','back','drag','action','stop'):
            with self.subTest(mode=mode):
                self.setUp();e=dict(time=self.events[2]['time'],stage=self.o['key'])
                if mode in ('back','drag','stop'):e['kind']=mode
                elif mode=='action':e.update(kind='action',action='未通关验证通过，准备战斗')
                else:e.update(kind='screen',screen=mode)
                self.events.insert(3,e);self.assertIsNone(self.read())
    def test_no_reward_close_or_unrelated_stage_is_not_a_story_result(self):
        for mode in ('no_reward','no_close','wrong_stage','two_opens'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode=='no_reward':self.events=[e for e in self.events if e.get('screen')!='story_reward']
                elif mode=='no_close':self.events=[e for e in self.events if e.get('action')!='关闭已发放的免费奖励遮罩']
                elif mode=='wrong_stage':self.events[-2]['stage']='other'
                else:self.events.insert(1,copy.deepcopy(self.events[0]))
                self.assertIsNone(self.read())
    def test_sparse_wrong_number_spacing_unlocked_next_or_other_chapter_is_rejected(self):
        for mode in ('missing','duplicate','number','spacing','unlocked','chapter','selected_clear'):
            with self.subTest(mode=mode):
                self.setUp()
                if mode=='missing':self.rows.pop()
                elif mode=='duplicate':self.rows.append(copy.deepcopy(self.rows[0]))
                elif mode=='number':self.rows[1]['stage']+=1
                elif mode=='spacing':self.rows[1]['y']+=10
                elif mode=='unlocked':self.rows[1]['locked']=False
                elif mode=='chapter':self.d['chapter']+=1
                else:self.d['clear_badge']=True
                self.assertIsNone(self.read())
    def test_unknown_overlay_vetoes_underlying_green_badge(self):
        self.f.words.append(dict(text='点击关闭',score=.99,x=800,y=600,box=[]));self.assertIsNone(self.read())
    def test_runner_records_only_current_story_result_and_never_reopens_it(self):
        r=fake_runner(self.f);r.s=self.s;r.run_id='synthetic-run';r.map_ticket=lambda f:(self.d,self.rows,'未通关蓝色当前节点')
        (self.root/'events.jsonl').write_text('\n'.join(json.dumps(e,ensure_ascii=False) for e in self.events),encoding='utf8')
        original=copy.deepcopy(r.s['attempted']);sent=copy.deepcopy(r.s['entry_dispatches'])
        with patch.object(runner,'ROOT',self.root),patch('runner.event'),patch('story_open_ack.binding',return_value=self.binding):r.step(self.f)
        self.assertIn(self.o['key'],r.s['completed']);self.assertIsNone(r.s['active'])
        self.assertEqual(r.s['attempted'],original);self.assertEqual(r.s['entry_dispatches'],sent)
        self.assertEqual(r.action.call_count,1);self.assertEqual(r.action.call_args.args[0],'未通关验证通过，准备战斗')
    def test_later_gameplay_is_not_credited_or_failed_from_an_old_story_dispatch(self):
        for scene in ('battle','victory','settlement'):
            with self.subTest(scene=scene):
                r=fake_runner(self.f);r.s=copy.deepcopy(self.s);before=copy.deepcopy(r.s)
                with patch.object(runner,'ROOT',self.root),patch('runner.event'),patch('runner.classify',return_value=scene):
                    self.assertTrue(r.step(self.f)[0])
                self.assertEqual(r.s['completed'],{});self.assertIsNotNone(r.s['active'])
                self.assertNotIn('stage_outcomes',r.s)
    def test_optional_original_private_snapshot_replay_is_not_runtime_reconciliation(self):
        base=Path(__file__).resolve().parents[1]/'.local/clipped-result-20261106'
        if not (base/'replay-state.json').is_file():self.skipTest('private original source unavailable')
        state=json.loads((base/'replay-state.json').read_text(encoding='utf8'));events=json.loads((base/'replay-events.json').read_text(encoding='utf8'))
        request=json.loads((base/'source/request.json').read_text(encoding='utf8'));root=Path(request['settings']['data_dir'])
        from rapidocr_onnxruntime import RapidOCR
        image=runner.cv2.imdecode(runner.np.frombuffer((base/'original-map.png').read_bytes(),runner.np.uint8),1)
        results,_=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)(image);f=runner.Frame(image,results)
        d,rows,_=runner.Runner.__new__(runner.Runner).map_ticket(f);a=state['active'];ack=state['story_open_acknowledgements'][state['entry_dispatches'][a['key']][0]['id']]
        proof=recorded_clipped_story_completion(f,state,d,rows,events,run_id=ack['run_id'],current_binding=ack['binding'],root=root)
        self.assertIsNotNone(proof);self.assertEqual(proof['stage'],6);self.assertFalse(proof['clickable']);self.assertIsNone(proof['star_count'])

if __name__=='__main__':unittest.main()
