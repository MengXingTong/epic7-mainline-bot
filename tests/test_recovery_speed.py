"""Offline regressions only: fake windows, inputs, UAC and private temporary state."""
import copy,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
import runner
from assistant_config import atomic_json,validate_run,load_settings
from assistant_worker import Control,StopRun,acknowledge_previous_stop
from task_blockers import capacity_blocker,TaskAttention
from task_timing import TransitionPacer,next_delay,ObservationCycle
from task_overlays import rankup_splash
from windows_elevation import ensure_administrator,RELAUNCH_FLAG
from abyss_core import Observation,Token,Scene,Session,classify as abyss_classify

RANK=[dict(text=t,x=x,y=y) for t,x,y in [('RANKUP',802,272),('23',804,337),('账号Rank提升，已恢复97点行动力。',800,776),('请继续您的旅程吧！',803,810)]]
def frame(words):
    results=[([[w['x']-20,w['y']-10],[w['x']+20,w['y']-10],[w['x']+20,w['y']+10],[w['x']-20,w['y']+10]],w['text'],.999) for w in words]
    return runner.Frame(runner.np.zeros((900,1600,3),runner.np.uint8),results)
def fake_runner():
    r=runner.Runner.__new__(runner.Runner)
    r.s={'attempted':{'E3-C3-S10':{'key':'E3-C3-S10','stage':10,'episode':3,'chapter':3,'evidence':'keep.png'}},'completed':{},'active':{'key':'E3-C3-S10','stage':10,'episode':3,'chapter':3},'last_cleared':{'episode':5,'chapter':1,'stage':1},'terminal':True,'reason':'old failure','stop_evidence':'keep.png'}
    r.cfg={'start_policy':'current_screen'};r.ticket=None;r.last_mode=None;r.mode_since=time.time();r.unknown_gestures=0
    r.save=Mock();r.evidence=Mock(return_value='new-evidence.png');r.action=Mock();r.back=Mock()
    return r

class BlockerTests(unittest.TestCase):
    def test_common_capacity_not_a_defeat(self):
        for text in ['装备背包已满','装备数量已达上限','神器持有上限','英雄栏空间不足','背包容量不足','裝備已滿']:
            with self.subTest(text=text):
                self.assertIsNotNone(capacity_blocker([text]))
                words=[dict(text=text,x=800,y=400),dict(text='挑战失败',x=800,y=500),dict(text='确认',x=900,y=600)]
                self.assertEqual(runner.classify(frame(words)),'capacity_stop')
                o=Observation(1600,900,[Token(w['text'],w['x']-20,w['y']-10,40,20) for w in words])
                self.assertEqual(abyss_classify(o).scene,Scene.CAPACITY)
                with self.assertRaises(TaskAttention):Session().plan(abyss_classify(o),o)
    def test_unrelated_max_level_or_upgrade_failure_not_capacity(self):
        for text in ['英雄已满级','英雄满级','装备强化失败','装备可扩充至500','装备强化达到15级','英雄数量 250/300']:
            self.assertIsNone(capacity_blocker([text]),text)
    def test_capacity_wait_keeps_entry_and_completion_records(self):
        r=fake_runner();before=copy.deepcopy(r.s)
        with patch('runner.event'),patch.object(runner,'ROOT',Path('not-existing-test-root')):
            with self.assertRaises(TaskAttention):r.step(frame([dict(text='装备背包已满',x=800,y=400)]))
        self.assertFalse(r.s['terminal']);self.assertEqual(r.s['active'],before['active'])
        for k in ['attempted','completed','last_cleared']:self.assertEqual(r.s[k],before[k])
        r.action.assert_not_called();r.save.assert_called_once()

class CurrentScreenTests(unittest.TestCase):
    def test_restart_preserves_failure_and_does_not_fabricate_clear(self):
        r=fake_runner();before=copy.deepcopy(r.s);r.start_current_screen()
        self.assertEqual(r.s['resume_audit'][0]['previous'],before)
        self.assertEqual(r.s['unresolved_entries'][0]['entry'],before['active'])
        self.assertIsNone(r.s['active']);self.assertFalse(r.s['terminal'])
        for k in ['attempted','completed','last_cleared','stop_evidence']:self.assertEqual(r.s[k],before[k])
        r.completed('unowned result must not clear the old stage');self.assertEqual(r.s['completed'],{})
        r.action.assert_not_called()
    def test_map_new_stage_does_not_read_old_green_or_require_old_order(self):
        r=fake_runner();r.start_current_screen();r.map_ticket=Mock(return_value=(dict(key='E3-C5-S8',episode=3,chapter=5,stage=8,name='new',verified_epoch=time.time()),[], '未通关蓝色当前节点'))
        with patch('runner.classify',return_value='map'),patch('runner.event'),patch.object(runner,'ROOT',Path('not-existing-test-root')):keep,_=r.step(frame([]))
        self.assertTrue(keep);r.action.assert_called_once();self.assertEqual(r.s['completed'],{})
    def test_attempted_current_node_is_not_mistaken_for_completed(self):
        r=fake_runner();r.start_current_screen();r.map_ticket=Mock(return_value=(dict(key='E3-C3-S10',episode=3,chapter=3,stage=10),[dict(stage=11,green=0,x=320,y=350,lock_score=.95,locked=True)],'未通关蓝色当前节点'))
        with patch('runner.classify',return_value='map'),patch('runner.event'),patch.object(runner,'ROOT',Path('not-existing-test-root')):
            with self.assertRaises(TaskAttention) as caught:r.step(frame([]))
        self.assertEqual(caught.exception.code,'current_stage_unresolved');r.action.assert_not_called();self.assertIsNone(r.ticket)
    def test_current_policy_admits_stopped_history_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);state=fake_runner().s;atomic_json(root/'state.json',state);(root/'STOP').write_text('user stop')
            _,result=validate_run(dict(data_dir=d,task='mainline',limit=3,pc_input='messages',observe=False,start_policy='current_screen'),{'client':'pc'})
            self.assertEqual(result,state);self.assertTrue((root/'STOP').exists())

class AttentionControlTests(unittest.TestCase):
    def test_wait_needs_a_fresh_run_command_and_stop_always_wins(self):
        for final in ['run','stop']:
            with tempfile.TemporaryDirectory() as d:
                ctl=Control(dict(run_dir=d,run_id='test',settings={'task':'mainline'},target={'client':'mumu'}))
                path=Path(d)/'control.json';old={'run_id':'test','action':'run','command_id':'old'};atomic_json(path,old)
                calls=[]
                def advance(_):
                    calls.append(1)
                    if len(calls)==1:self.assertEqual(json.loads(path.read_text()),old)
                    else:atomic_json(path,{'run_id':'test','action':final,'command_id':'new'})
                with patch('assistant_worker.time.sleep',side_effect=advance):
                    if final=='stop':
                        with self.assertRaises(StopRun):ctl.attention(TaskAttention('capacity','装备已满','手动处理'))
                    else:ctl.attention(TaskAttention('capacity','装备已满','手动处理'))
                self.assertEqual(len(calls),2)
    def test_old_stop_archived_only_after_new_explicit_start(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);marker=root/'STOP';marker.write_text('keep exact bytes')
            req={'settings':{'observe':False},'user_selected_profile':True,'requested_at':time.time()+1,'run_id':'new'}
            acknowledge_previous_stop(root,req,Mock());self.assertFalse(marker.exists());self.assertEqual((root/'STOP.previous-new').read_text(),'keep exact bytes')
    def test_new_stop_after_start_is_not_consumed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'STOP').write_text('new stop')
            req={'settings':{'observe':False},'user_selected_profile':True,'requested_at':time.time()-10,'run_id':'new'}
            with self.assertRaises(StopRun):acknowledge_previous_stop(root,req,Mock())
            self.assertTrue((root/'STOP').exists())
    def test_preview_is_encoded_at_small_size(self):
        with tempfile.TemporaryDirectory() as d:
            ctl=Control(dict(run_dir=d,run_id='test',settings={'task':'mainline'},target={'client':'pc'}));source=Image.new('RGB',(1920,1080))
            ctl.preview(source)
            with Image.open(Path(d)/'preview.png') as im:self.assertEqual(im.size,(560,315))
            self.assertEqual(source.size,(1920,1080))

class TimingTests(unittest.TestCase):
    def test_all_ordinary_scenes_use_quarter_second_business_backoff_unchanged(self):
        for scene in ('map','team','battle','loading','result_transition','unknown','story','settlement'):
            for acted in (True,False):
                self.assertEqual(next_delay(scene,5,acted),.25)
        self.assertEqual(next_delay('network_error',10,True),10)
        self.assertEqual(next_delay('natural_resource_wait',60),60)
    def test_cycle_counts_capture_recognition_and_writes_toward_budget(self):
        now=[100.0];cycle=ObservationCycle(lambda:now[0]);ctl=Mock()
        now[0]+=.1;cycle.wait(ctl)
        self.assertAlmostEqual(ctl.sleep.call_args.args[0],.15)
    def test_slow_cycle_never_adds_wait_or_catches_up_next_cycle(self):
        now=[100.0];cycle=ObservationCycle(lambda:now[0]);ctl=Mock()
        now[0]+=.4;cycle.wait(ctl);ctl.sleep.assert_not_called()
        cycle.begin();now[0]+=.05;cycle.wait(ctl)
        self.assertAlmostEqual(ctl.sleep.call_args.args[0],.2)
    def test_cycle_wait_propagates_stop(self):
        cycle=ObservationCycle(lambda:100);ctl=Mock();ctl.sleep.side_effect=StopRun()
        with self.assertRaises(StopRun):cycle.wait(ctl)
    def test_repeated_same_scene_waits_but_new_scene_immediate(self):
        clock=Mock(return_value=100);p=TransitionPacer(clock);p.applied('map')
        clock.return_value=101;self.assertTrue(p.waiting('map'));self.assertFalse(p.waiting('support'))
    def test_new_capacity_popup_never_hidden_by_entry_wait(self):
        p=TransitionPacer(lambda:100);p.applied('team',entry=True);self.assertTrue(p.waiting('team'));self.assertFalse(p.waiting('capacity_stop'))
    def test_entry_gets_full_grace_period_without_reclicks(self):
        clock=Mock(return_value=100);p=TransitionPacer(clock);p.applied('team',entry=True);clock.return_value=114
        self.assertTrue(p.waiting('team'));clock.return_value=116;self.assertFalse(p.waiting('team'))

class RankUpTests(unittest.TestCase):
    def test_actual_user_ocr_text_matches_splash_without_confirm(self):
        self.assertTrue(rankup_splash(RANK));self.assertEqual(runner.classify(frame(RANK)),'rankup_splash')
        r=fake_runner()
        with patch('runner.event'),patch.object(runner,'ROOT',Path('not-existing-test-root')):keep,_=r.step(frame(RANK))
        self.assertTrue(keep);self.assertEqual(r.action.call_args.kwargs['xy'],(800,872))
    def test_rank_label_alone_and_purchase_dialog_never_dismissed(self):
        self.assertFalse(rankup_splash(RANK[:2]));self.assertFalse(rankup_splash(RANK[2:]))
        self.assertEqual(runner.classify(frame(RANK+[dict(text='购买体力',x=800,y=400)])),'resource_stop')
        self.assertFalse(rankup_splash(RANK+[dict(text='确认',x=800,y=400)]))
        o=Observation(1600,900,[Token(w['text'],w['x']-20,w['y']-10,40,20) for w in RANK+[dict(text='购买',x=800,y=400)]])
        self.assertEqual(abyss_classify(o).scene,Scene.BLOCKED)
    def test_abyss_rankup_does_not_change_floor_or_record_win(self):
        o=Observation(1600,900,[Token(w['text'],w['x']-20,w['y']-10,40,20) for w in RANK]);s=Session(expected_floor=52,phase='battle')
        reading=abyss_classify(o,True);self.assertEqual(reading.scene,Scene.RANKUP)
        action=s.plan(reading,o);self.assertEqual(action.key,'rankup-continue');self.assertEqual(s.expected_floor,52);self.assertEqual(s.wins,0)

class ElevationTests(unittest.TestCase):
    def api(self,admin=False,result=(42,0)):
        api=Mock();api.is_admin.return_value=admin;api.launch.return_value=result;return api
    def test_already_admin_no_relaunch(self):
        api=self.api(True);self.assertEqual(ensure_administrator('portable_entry.py',[],api),'continue');api.launch.assert_not_called()
    def test_standard_runas_once_with_quoted_chinese_path_and_args(self):
        api=self.api();self.assertEqual(ensure_administrator(Path('中文 空格')/'portable_entry.py',['--client','pc'],api,executable='pythonw.exe'),'relaunched')
        api.launch.assert_called_once();exe,params,cwd=api.launch.call_args.args
        self.assertIn('"',params);self.assertIn('中文 空格',params);self.assertIn('--client pc',params);self.assertIn(RELAUNCH_FLAG,params)
    def test_cancel_does_not_continue_or_request_again(self):
        api=self.api(result=(5,1223));self.assertEqual(ensure_administrator('portable_entry.py',[],api),'cancelled');api.launch.assert_called_once()
    def test_relaunch_guard_never_loops(self):
        api=self.api()
        with self.assertRaises(RuntimeError):ensure_administrator('portable_entry.py',[RELAUNCH_FLAG],api)
        api.launch.assert_not_called()
    def test_readonly_ui_check_does_not_request_uac(self):
        api=self.api();self.assertEqual(ensure_administrator('portable_entry.py',['--ui-check'],api),'continue');api.is_admin.assert_not_called();api.launch.assert_not_called()
    def test_saved_foreground_is_migrated_to_background(self):
        with tempfile.TemporaryDirectory() as d:
            atomic_json(Path(d)/'settings.json',{'pc_input':'foreground','observe':True})
            with patch('assistant_portable.enabled',return_value=False):s=load_settings(Path(d))
            self.assertEqual(s['pc_input'],'messages');self.assertFalse(s['observe']);self.assertEqual(s['start_policy'],'current_screen')

class CaptureRecoveryTests(unittest.TestCase):
    def test_temporary_black_frames_retry_capture_only(self):
        from assistant_worker import capture_fresh
        from pc_message_backend import CaptureUnavailable
        capture=Mock(side_effect=[CaptureUnavailable('blank'),CaptureUnavailable('blank'),'new frame']);ctl=Mock()
        self.assertEqual(capture_fresh(capture,ctl,clock=Mock(side_effect=[0,1])),'new frame')
        self.assertEqual(capture.call_count,3);self.assertEqual(ctl.sleep.call_count,2);ctl.attention.assert_not_called()
    def test_other_target_or_geometry_errors_are_not_retried(self):
        from assistant_worker import capture_fresh
        from pc_backend import PcSafetyError
        capture=Mock(side_effect=PcSafetyError('geometry changed'));ctl=Mock()
        with self.assertRaises(PcSafetyError):capture_fresh(capture,ctl)
        capture.assert_called_once();ctl.sleep.assert_not_called();ctl.attention.assert_not_called()
    def test_persistent_black_capture_waits_for_user_not_silent_hang(self):
        from assistant_worker import capture_fresh
        from pc_message_backend import CaptureUnavailable
        capture=Mock(side_effect=CaptureUnavailable('blank'));ctl=Mock();ctl.attention.side_effect=StopRun()
        with self.assertRaises(StopRun):capture_fresh(capture,ctl,clock=Mock(side_effect=[0,11]))
        self.assertEqual(ctl.attention.call_args.args[0].code,'capture');self.assertEqual(capture.call_count,2)
    def test_actual_reward_text_takes_priority_over_background_map(self):
        r=fake_runner();words=[dict(text=t,x=x,y=y) for t,x,y in [('Episode 3',154,44),('完成故事',800,218),('故事完成奖励已正常发放。',801,319),('点击关闭',802,600),('准备战斗',1390,826)]]
        f=frame(words);self.assertEqual(runner.classify(f),'story_reward')
        with patch('runner.event'),patch.object(runner,'ROOT',Path('not-existing-test-root')):keep,_=r.step(f)
        self.assertTrue(keep);self.assertIn('奖励遮罩',r.action.call_args.args[0]);self.assertEqual(r.action.call_args.args[1]['text'],'点击关闭')
