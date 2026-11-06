"""Only a positively unsent ordinary UI tap may replan after a global key race."""
import copy,os,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import runner
from pc_backend import TapNotSent,InputBusy,InputDeliveryError,PcSafetyError,NavigationInputDeferred
from assistant_worker import mainline_run,client_attention,StopRun
from test_story_only_nodes import fake_runner,frame
import test_input_ux as input_ux


class DeferredUiInputTests(unittest.TestCase):
    ordinary={'未通关验证通过，准备战斗':'map','避开已通关关卡，选择下一关':'map',
              '完成本章后进入下一章':'map','选择当前队伍':'support',
              '确认通关结算':'settlement','关闭已发放的免费奖励遮罩':'story_reward','跳过剧情':'story','确认跳过剧情':'skip_confirm','通关星级页继续至结算':'victory'}
    def make(self,scene='settlement'):
        r=fake_runner(frame());r.action=runner.Runner.action.__get__(r,runner.Runner);r.pc=SimpleNamespace();r.s['screen']=scene
        r._action=Mock(side_effect=TapNotSent('检测到全局按住状态：鼠标左键'))
        return r
    def test_each_known_unsent_ui_action_is_deferred_without_entry_or_completed_mutation(self):
        for action,scene in self.ordinary.items():
            with self.subTest(action=action):
                r=self.make(scene);before=copy.deepcopy(r.s)
                with patch.object(runner,'event') as event:
                    with self.assertRaises(NavigationInputDeferred):r.action(action,{'x':10,'y':20})
                self.assertEqual(r.s,before);event.assert_called_once()
                self.assertEqual(event.call_args.kwargs['proof'],'TapNotSent_before_button_down')
    def test_story_skip_and_result_ui_taps_may_defer_with_recorded_active_without_entry_resend(self):
        for action,scene in (('跳过剧情','story'),('确认跳过剧情','skip_confirm'),('通关星级页继续至结算','victory')):
            with self.subTest(action=action):
                r=self.make(scene);r.s['active']=dict(key='recorded-original',cost=8);before=copy.deepcopy(r.s)
                with patch.object(runner,'event'):
                    with self.assertRaises(NavigationInputDeferred):r.action(action,{'x':10,'y':20})
                self.assertEqual(r.s,before)
    def test_wrong_scene_unknown_action_and_any_active_entry_remain_manual(self):
        for mode in ('scene','unknown','paid_active','story_active','no_pc'):
            with self.subTest(mode=mode):
                r=self.make();action='确认通关结算'
                if mode=='scene':r.s['screen']='unknown_dialog'
                elif mode=='unknown':action='未知确认'
                elif mode in ('paid_active','story_active'):r.s['active']=dict(key='original',entry_kind='story_only' if mode=='story_active' else 'battle',cost=0 if mode=='story_active' else 8)
                else:r.pc=None
                with patch.object(runner,'event') as event:
                    with self.assertRaises(TapNotSent) as caught:r.action(action,{'x':10,'y':20})
                self.assertNotIsInstance(caught.exception,NavigationInputDeferred);event.assert_not_called()
    def test_entry_journaled_close_skip_hold_and_unknown_actions_never_use_auto_path(self):
        actions=('进行任务（仅一次入场）','观看故事（仅一次）','关闭已核实的免费提示（不代表关卡通关）',
                 '确认首次战斗战力提示','重新进行','购买','未知动作')
        for action in actions:
            with self.subTest(action=action):
                r=self.make()
                with patch.object(runner,'event') as event:
                    with self.assertRaises(TapNotSent) as caught:r.action(action,{'x':10,'y':20})
                self.assertNotIsInstance(caught.exception,NavigationInputDeferred);event.assert_not_called()
    def test_generic_busy_delivery_window_or_critical_write_failure_is_not_recoverable(self):
        for exc in (InputBusy('may already be down'),InputDeliveryError('unknown delivery'),PcSafetyError('window changed'),OSError('critical write failed')):
            with self.subTest(exc=exc):
                r=self.make();r._action.side_effect=exc
                with patch.object(runner,'event') as event:
                    with self.assertRaises(type(exc)) as caught:r.action('确认通关结算',{'x':10,'y':20})
                self.assertNotIsInstance(caught.exception,NavigationInputDeferred);event.assert_not_called()
    def test_unsent_event_write_failure_cannot_be_swallowed_as_navigation_recovery(self):
        r=self.make()
        with patch.object(runner,'event',side_effect=OSError('evidence denied')):
            with self.assertRaises(OSError):r.action('确认通关结算',{'x':10,'y':20})
        r._action.assert_called_once()
    def test_settlement_retry_does_not_recount_or_reopen_the_finished_stage(self):
        r=self.make();r.s['active']=dict(key='original',name='synthetic',cost=8);r.s['victories']=0
        def attempt(*args,**kwargs):
            self.assertIsNone(r.s['active']);self.assertIn('original',r.s['completed'])
            if r._action.call_count==1:raise TapNotSent('global left button')
        r._action.side_effect=attempt
        with patch.object(runner,'classify',return_value='settlement'),patch.object(runner,'battle_settlement_confirm',return_value={'x':10,'y':20}),patch.object(runner,'event'):
            with self.assertRaises(NavigationInputDeferred):r.step(r.frame)
            completed=copy.deepcopy(r.s['completed']);victories=r.s['victories']
            r.frame=frame();r.step(r.frame)
        self.assertEqual(r.s['completed'],completed);self.assertEqual(r.s['victories'],victories)
        self.assertEqual(r.s['attempted'],{});self.assertEqual(r._action.call_count,2)
    def test_worker_deferred_ui_conflict_recaptures_without_attention_or_manual_continue(self):
        instances=[]
        class FakeRunner:
            def __init__(self,**kwargs):
                self.pc=None;self.s=dict(completed={},attempted={'old':{'keep':True}},active=None,screen='settlement');self.ticket=None;self.mode_since=0;self.input_sequence=0;self.frames=[];instances.append(self)
            def start_current_screen(self):pass
            def capture(self):
                f=runner.Frame(runner.np.full((900,1600,3),22,runner.np.uint8),[]);self.frames.append(f);return f
            def step(self,f):
                if len(self.frames)==1:raise NavigationInputDeferred('检测到全局按住状态：Ctrl')
                return False,0
            def save(self):pass
        ctl=Mock();story=SimpleNamespace(total_wins=lambda:0,context=False,stage_label=lambda:'')
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=False):
            root=Path(folder);request=dict(run_dir=folder,settings=dict(observe=False,task='mainline',mumu={}),target=dict(client='mumu',serial='fake',package='fake'))
            with patch('assistant_worker.validate_run',return_value=(root,{})),patch.object(runner,'ROOT',root),patch.object(runner,'Runner',FakeRunner),patch.object(runner,'classify',return_value='settlement'),patch('story_core.StoryController',return_value=story):
                mainline_run(request,ctl)
        ctl.attention.assert_not_called();self.assertEqual(len(instances[0].frames),2)
        self.assertIsNot(instances[0].frames[0],instances[0].frames[1]);self.assertEqual(instances[0].s['attempted'],{'old':{'keep':True}})
        self.assertTrue(any(c.kwargs.get('mode')=='waiting_input' for c in ctl.status.call_args_list))
    def test_uncertain_input_message_reports_reason_without_asserting_game_takeover(self):
        result=client_attention(InputBusy('synthetic global key conflict'))
        self.assertNotIn('输入被接管',result.title);self.assertIn('其他窗口',result.reason)
        self.assertIn('synthetic global key conflict',result.reason);self.assertIn('点继续',result.reason)
    def test_real_action_top_level_expiry_is_typed_and_replans_support_without_sending(self):
        from pc_backend import NavigationFrameExpired,FrameExpired
        r=self.make('support');r._action=runner.Runner._action.__get__(r,runner.Runner)
        r.ensure_game=Mock();r.frame.at=time.time()-6
        with patch.object(runner,'event') as event:
            with self.assertRaises(NavigationFrameExpired):r.action('选择当前队伍',{'x':10,'y':20})
        event.assert_not_called();self.assertEqual(r.s['attempted'],{})
        r.s['screen']='team'
        with self.assertRaises(FrameExpired) as caught:r.action('进行任务（仅一次入场）',{'x':10,'y':20})
        self.assertNotIsInstance(caught.exception,NavigationFrameExpired)
    def test_typed_expiry_does_not_replan_entry_unknown_actions_or_active_navigation(self):
        from pc_backend import NavigationFrameExpired,FrameExpired
        for mode in ('unknown','entry','active'):
            with self.subTest(mode=mode):
                r=self.make('support');r._action.side_effect=FrameExpired('unsent stale frame')
                action='选择当前队伍'
                if mode=='unknown':r.s['screen']='unknown_dialog'
                elif mode=='entry':action='进行任务（仅一次入场）'
                else:r.s['active']={'key':'keep'}
                with self.assertRaises(FrameExpired) as caught:r.action(action,{'x':10,'y':20})
                self.assertNotIsInstance(caught.exception,NavigationFrameExpired)

    def test_global_key_labels_explain_other_window_conflict_without_tracking_motion(self):
        fixture=input_ux.PhysicalInputTests();api=fixture.make()
        for key,label in ((1,'鼠标左键'),(2,'鼠标右键'),(4,'鼠标中键'),(5,'鼠标侧键1'),(6,'鼠标侧键2'),(0x10,'Shift'),(0x11,'Ctrl'),(0x12,'Alt')):
            with self.subTest(key=key):
                fixture.pressed={key};reason=api.input_block_reason(api.target)
                self.assertIn(label,reason);self.assertIn('全局',reason);self.assertIn('其他窗口',reason)
        fixture.pressed=set();fixture.pointer[:]=[-1700,200];self.assertEqual(api.input_block_reason(api.target),'')
        fixture.pointer[:]=[-1800,300];self.assertEqual(api.input_block_reason(api.target),'')
        api.u.SetCursorPos.assert_not_called();api.u.SendInput.assert_not_called()

if __name__=='__main__':unittest.main()
