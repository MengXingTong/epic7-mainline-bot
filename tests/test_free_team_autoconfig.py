"""Exact no-cost team configuration; never an entry or protected-object action."""
import copy,time,unittest
from unittest.mock import Mock
from test_map_layout import frame
from task_blockers import TaskAttention
from tutorial_core import tutorial_plan,TutorialController
import runner


def current():
    return frame([('自动配置',803,272),('新的队伍栏位尚未配置英雄。',800,421),('可自动配置高战斗力的英雄。',800,448),('是否进行配置？',800,475),('取消',667,619),('确认',935,619)])


class FreeTeamAutoConfigurationTests(unittest.TestCase):
    def controller(self):
        r=Mock();r.ticket=None;r.evidence.return_value='synthetic'
        r.s={'active':None,'last_stage':'E6-C3-S4','verified':dict(key='E6-C3-S4',phase='map',proof='未通关蓝色当前节点',evidence='synthetic-map',locked=False,clear_badge=False),'attempted':{},'completed':{}}
        r.attention.side_effect=lambda *a:(_ for _ in ()).throw(TaskAttention(*a));return r,TutorialController(r)
    def dispatch(self,c):
        # Separate synthetic capture times even on Windows' coarse wall clock.
        first=current();first.at-=.25;c.step(first);return c.step(current())
    def test_only_exact_free_configuration_is_known(self):
        p=tutorial_plan(current());self.assertEqual(p['rule'],'free_team_auto_configuration');self.assertEqual(p['target']['text'],'确认')
        self.assertEqual(runner.classify(current()),'new_player_tutorial')
        for i in range(6):
            for mode in ('missing','weak','duplicate','moved'):
                f=current()
                if mode=='missing':f.words.pop(i)
                if mode=='weak':f.words[i]['score']=.979
                if mode=='duplicate':f.words.append(copy.deepcopy(f.words[i]))
                if mode=='moved':f.words[i]['y']=30
                self.assertIsNone(tutorial_plan(f),(i,mode))
        for text in ('购买','是否消耗','战斗失败','装备背包已满','额外扣除金币10','未知说明'):
            f=current();f.words+=frame([(text,800,350)]).words;self.assertIsNone(tutorial_plan(f))
    def test_one_current_frame_durable_per_stage_single_send_progress_immutable(self):
        r,c=self.controller();old=copy.deepcopy(r.s);record=[]
        r.action.side_effect=lambda *a:record.append(copy.deepcopy(r.s))
        f=current();f.at-=.25;c.step(f);c.step(f);r.action.assert_called_once();c.step(current());r.action.assert_called_once()
        self.assertEqual(record[0]['tutorial']['auto_configurations']['E6-C3-S4']['status'],'reserved')
        self.assertEqual(r.s['tutorial']['auto_configurations']['E6-C3-S4']['status'],'sent')
        self.assertEqual(r.s['tutorial']['auto_configurations']['E6-C3-S4']['map_source'],old['verified'])
        for k in old:self.assertEqual(r.s[k],old[k])
        self.dispatch(TutorialController(r));r.action.assert_called_once()
    def test_wrong_missing_cleared_locked_or_attempted_map_has_no_input(self):
        for mode in ('none','stage','phase','proof','evidence','locked','clear','active','attempted','completed'):
            r,c=self.controller()
            if mode=='none':r.s['verified']={}
            elif mode=='stage':r.s['last_stage']='other'
            elif mode=='phase':r.s['verified']['phase']='team'
            elif mode=='proof':r.s['verified']['proof']='unconfirmed'
            elif mode=='evidence':r.s['verified']['evidence']=''
            elif mode=='locked':r.s['verified']['locked']=True
            elif mode=='clear':r.s['verified']['clear_badge']=True
            elif mode=='active':r.s['active']={'key':'other'}
            else:r.s[mode]['E6-C3-S4']={}
            with self.assertRaises(TaskAttention):self.dispatch(c)
            r.action.assert_not_called()
    def test_save_failure_and_send_unknown_are_not_retried(self):
        r,c=self.controller();r.save.side_effect=OSError('full')
        with self.assertRaises(OSError):self.dispatch(c)
        r.action.assert_not_called()
        r,c=self.controller();r.action.side_effect=RuntimeError('unknown')
        with self.assertRaises(RuntimeError):self.dispatch(c)
        r.action.reset_mock();r.action.side_effect=None;self.dispatch(TutorialController(r));r.action.assert_not_called()
    def test_stale_frame_has_no_input(self):
        r,c=self.controller();f=current();f.at=time.time()-8;c.step(f);r.action.assert_not_called()

if __name__=='__main__':unittest.main()
