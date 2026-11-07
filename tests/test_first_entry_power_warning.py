import copy,datetime,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from entry_journal import attempt_digest
from test_map_layout import frame
from task_blockers import TaskAttention
from tutorial_core import tutorial_plan,TutorialController
from tutorial_battle_confirmation import confirmation_source


def current():
    return frame([('战斗指南',800,244),('登场的敌方战斗力',802,359),('比我方队伍高出许多。',795,387),('要继续进行吗？',800,440),('点击不再显示按钮，今日内将不再显示弹窗，',800,520),('并开始战斗。',800,547),('取消',528,665),('确认',797,665),('不再显示',1067,664)])


class FirstEntryPowerWarningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.path=self.root/'events.jsonl'
        self.original=dict(key='stage',cost=8,stamina_before=680,start_epoch=time.time()-10,team_entry_mode='single_task',proof='未通关蓝色当前节点')
        self.state={'active':copy.deepcopy(self.original),'attempted':{'stage':copy.deepcopy(self.original)},'completed':{},'entry_dispatches':{'stage':[dict(status='sent',entry=copy.deepcopy(self.original),original_sha256=attempt_digest(self.original))]}}
        self.events=[dict(time=datetime.datetime.fromtimestamp(self.original['start_epoch']).astimezone().isoformat(),kind='action',stage='stage',action='进行任务（仅一次入场）')]
        self.save_events();self.patch=patch('runner.ROOT',self.root);self.patch.start()
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def save_events(self):self.path.write_text(''.join(json.dumps(e,ensure_ascii=False)+'\n' for e in self.events),encoding='utf8')
    def controller(self):
        r=Mock();r.s=copy.deepcopy(self.state);r.evidence.return_value='synthetic';r.attention.side_effect=lambda *a:(_ for _ in ()).throw(TaskAttention(*a));return r,TutorialController(r)
    def dispatch(self,c):c.step(current());return c.step(current())
    def test_complete_exact_warning_targets_confirm_never_dont_show_again(self):
        p=tutorial_plan(current());self.assertEqual(p['rule'],'first_entry_power_warning');self.assertEqual(p['target']['text'],'确认')
        for i in range(9):
            for mode in ('missing','weak','duplicate','moved'):
                f=current()
                if mode=='missing':f.words.pop(i)
                elif mode=='weak':f.words[i]['score']=.979
                elif mode=='duplicate':f.words.append(copy.deepcopy(f.words[i]))
                else:f.words[i]['x']=100
                self.assertIsNone(tutorial_plan(f),(i,mode))
        for text in ('付费购买','是否消耗资源','未知附加说明','战斗失败','装备背包已满'):
            f=current();f.words+=frame([(text,800,400)]).words;self.assertIsNone(tutorial_plan(f),text)
    def test_source_requires_original_unique_sent_without_result_or_archive(self):
        self.assertEqual(confirmation_source(self.state,self.path)['key'],'stage')
        for mode in ('completed','attempt','duplicate','unknown','hash','archive','story','battle','cost'):
            s=copy.deepcopy(self.state)
            if mode=='completed':s['completed']['stage']={}
            elif mode=='attempt':s['attempted']['stage']={}
            elif mode=='duplicate':s['entry_dispatches']['stage']*=2
            elif mode=='unknown':s['entry_dispatches']['stage'][0]['status']='reserved'
            elif mode=='hash':s['entry_dispatches']['stage'][0]['original_sha256']='wrong'
            elif mode=='archive':s['unresolved_entries']=[{'entry':self.original}]
            else:s['active'][{'story':'entry_kind','battle':'battle_seen','cost':'cost'}[mode]]={'story':'story_only','battle':True,'cost':0}[mode]
            with self.assertRaises(ValueError):confirmation_source(s,self.path)
    def use_mode(self,mode):
        original=copy.deepcopy(self.original);original['team_entry_mode']=mode
        self.state.update(active=copy.deepcopy(original),attempted={'stage':copy.deepcopy(original)},
            entry_dispatches={'stage':[dict(status='sent',entry=copy.deepcopy(original),original_sha256=attempt_digest(original))]})
    def test_auto_on_first_entry_has_the_same_one_shot_confirmation(self):
        self.use_mode('auto_on')
        self.assertEqual(confirmation_source(self.state,self.path)['original']['team_entry_mode'],'auto_on')
        r,c=self.controller();before=copy.deepcopy(r.s);snap=[]
        r.action.side_effect=lambda *a:snap.append(copy.deepcopy(r.s))
        c.step(current());c.step(current());TutorialController(r).step(current())
        r.action.assert_called_once();self.assertEqual(r.action.call_args.args[1]['text'],'确认')
        self.assertEqual(snap[0]['entry_confirmations']['stage']['status'],'reserved')
        self.assertEqual(r.s['entry_confirmations']['stage']['status'],'sent')
        for key in before:self.assertEqual(r.s[key],before[key])
    def test_unverified_disabled_and_repeat_modes_never_confirm(self):
        for mode in ('unknown','enable_auto','hosted','repeat','',None):
            with self.subTest(mode=mode):
                self.use_mode(mode)
                with self.assertRaises(ValueError):confirmation_source(self.state,self.path)
                r,c=self.controller()
                with self.assertRaises(TaskAttention):c.step(current())
                r.action.assert_not_called()
    def test_any_other_input_or_unknown_battle_playback_result_or_error_chain_rejects(self):
        for extra in (dict(kind='action',action='other'),dict(kind='back'),dict(kind='error'),*[dict(kind='screen',screen=m) for m in ('story','battle','loading','unknown','victory','defeat','settlement')]):
            original=copy.deepcopy(self.events);self.events.append(dict(time=self.events[0]['time'],**extra));self.save_events()
            with self.assertRaises(ValueError):confirmation_source(self.state,self.path)
            self.events=original;self.save_events()
    def test_one_current_frame_durable_confirmation_and_no_new_entry(self):
        r,c=self.controller();old=copy.deepcopy(r.s);snap=[];r.action.side_effect=lambda *a:snap.append(copy.deepcopy(r.s))
        f=current();c.step(f);c.step(f);r.action.assert_called_once();c.step(current());r.action.assert_called_once()
        self.assertEqual(r.action.call_args.args[1]['text'],'确认')
        self.assertEqual(snap[0]['entry_confirmations']['stage']['status'],'reserved')
        for k in old:self.assertEqual(r.s[k],old[k])
        self.dispatch(TutorialController(r));r.action.assert_called_once()
    def test_unknown_send_or_save_failure_never_gets_second_confirm(self):
        r,c=self.controller();r.save.side_effect=OSError('full')
        with self.assertRaises(OSError):self.dispatch(c)
        r.action.assert_not_called()
        r,c=self.controller();r.action.side_effect=RuntimeError('unknown')
        with self.assertRaises(RuntimeError):self.dispatch(c)
        r.action.reset_mock();r.action.side_effect=None;self.dispatch(TutorialController(r));r.action.assert_not_called()

if __name__=='__main__':unittest.main()
