"""Owned-hero selector regressions. All input and persistence are mocked."""
import copy
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import runner
from pc_backend import TapNotSent
from story_core import team_entry_control
from task_blockers import TaskAttention
from test_map_layout import fake_runner, frame
from test_team_preparation import preparation, prepared_runner, step
from tutorial_core import (TutorialController, owned_hero_assignment_plan,
                           owned_hero_placement_verified, owned_hero_selector_visible,
                           selected_hero_position_plan, tutorial_plan)


SELECTOR=[('准备战斗',150,42),('等级',1330,117),('搜索',1525,117),
          ('不成熟的维多丽卡',1380,325),('进行任务',1430,827),('队伍战斗力',390,805)]


def selector(placed=False):
    f=frame(SELECTOR+([('已配置的英雄',800,847),('10',671,262)] if placed else []))
    # Current owned-card plus, NOT enough to prove a unit was placed.
    f.image[315:385,1160:1235]=(180,70,15)
    runner.cv2.rectangle(f.image,(1188,329),(1201,373),(0,220,255),-1)
    runner.cv2.rectangle(f.image,(1173,344),(1217,357),(0,220,255),-1)
    if placed:
        f.image[290:550,650:790]=(0,0,220)
        f.image[249:259,687:758]=(30,190,90)
        f.image[555:570,580:855]=(220,170,10)
    return f


def mock_plan(rule):
    target=dict(text=rule,x=1195,y=351,score=1.)
    return dict(rule=rule,label=rule,target=target,proof=[target,*([dict(text='新关卡',x=1239,y=161,score=.999)] if rule=='guided_owned_hero_slot' else [])])


def config_runner():
    r=prepared_runner(preparation());return r,TutorialController(r)


def dispatch(c,rule):
    with patch('tutorial_core.tutorial_plan',return_value=mock_plan(rule)):
        return c.step(frame())


class SelectorReaderTests(unittest.TestCase):
    def test_underlying_entry_never_authorized_with_any_selector_marker(self):
        for marker in SELECTOR[1:4]+[('已配置的英雄',800,847)]:
            f=preparation([marker])
            self.assertTrue(owned_hero_selector_visible(f))
            self.assertEqual(runner.classify(f),'team_hero_selection')
            self.assertEqual(team_entry_control(f)['kind'],'unknown')
            r=prepared_runner(f)
            with self.assertRaises(TaskAttention):step(r)
            r.action.assert_not_called();r.back.assert_not_called()
            self.assertEqual(r.s['attempted'],{'old-failure':{'outcome':'defeat','evidence':'preserve'}})

    def test_placed_hero_is_not_a_new_assignment_even_if_card_plus_remains(self):
        f=selector(True)
        self.assertTrue(owned_hero_placement_verified(f))
        self.assertIsNone(owned_hero_assignment_plan(f))
        self.assertIsNone(selected_hero_position_plan(f))
        self.assertIsNone(tutorial_plan(f))
        self.assertEqual(runner.classify(f),'team_hero_selection')
        self.assertIsNotNone(owned_hero_assignment_plan(selector()))

    def test_red_pixels_alone_missing_weak_duplicate_or_displaced_fields_fail(self):
        f=selector();f.image[270:555,645:790]=(0,0,220)
        self.assertFalse(owned_hero_placement_verified(f))
        for index in range(len(selector(True).words)):
            if index in (4,5):continue  # unrelated underlying entry/power labels
            for change in ('missing','weak','duplicate','displaced'):
                f=selector(True)
                if change=='missing':f.words.pop(index)
                elif change=='weak':f.words[index]['score']=.97
                elif change=='duplicate':f.words.append(dict(f.words[index]))
                else:f.words[index]['x']=900;f.words[index]['y']=600
                self.assertFalse(owned_hero_placement_verified(f),(index,change))
        for y1,y2,x1,x2 in ((290,550,645,790),(248,265,686,762),(490,625,575,860)):
            f=selector(True);f.image[y1:y2,x1:x2]=0
            self.assertFalse(owned_hero_placement_verified(f))

    def test_vetoes_still_outrank_complete_selector(self):
        for label,expected in [('确认','unknown_dialog'),('装备背包已满','capacity_stop'),
                               ('是否使用生命之叶补充体力','resource_stop'),('战斗失败','defeat')]:
            f=selector(True);f.words.extend(frame([(label,800,450)]).words)
            self.assertEqual(runner.classify(f),expected)


class TeamSetupChainTests(unittest.TestCase):
    def test_slot_transition_cannot_send_entry_or_back_to_map(self):
        r,c=config_runner();dispatch(c,'guided_owned_hero_slot');r.action.reset_mock()
        self.assertEqual(r.s['team_config']['phase'],'await_selector')
        for _ in range(3):step(r)
        r.action.assert_not_called();r.back.assert_not_called()
        self.assertIsNone(r.s['active']);self.assertNotIn(r.ticket['key'],r.s['attempted'])

    def test_each_setup_step_is_durable_once_despite_scene_flicker_and_restart(self):
        r,c=config_runner();saved=[]
        r.save.side_effect=lambda:saved.append(copy.deepcopy(r.s))
        for rule in ('guided_owned_hero_slot','assign_owned_victoria','place_selected_owned_hero'):
            dispatch(c,rule)
            self.assertEqual(saved[-2]['team_config']['dispatches'][rule]['status'],'reserved')
            self.assertEqual(r.s['team_config']['dispatches'][rule]['status'],'sent')
            count=r.action.call_count
            for scene in ('team','unknown','loading','team_hero_selection'):
                c.observe_scene(scene,frame())
                c=TutorialController(r)
                with patch('tutorial_core.tutorial_plan',return_value=mock_plan(rule)):
                    c.step(frame())
                self.assertEqual(r.action.call_count,count)
        self.assertEqual(r.action.call_count,3)
        self.assertNotIn(r.ticket['key'],r.s['attempted'])

    def test_new_stage_retains_completed_configuration_and_original_history(self):
        r,c=config_runner();old=dict(id='old-setup',stage_key='old-stage',phase='completed',
                                     evidence='keep.png',dispatches={'assign_owned_victoria':{'status':'sent'}})
        r.s['team_config']=copy.deepcopy(old);before=copy.deepcopy(r.s['attempted'])
        dispatch(c,'guided_owned_hero_slot')
        self.assertEqual(r.s['team_config_history'],[old])
        self.assertEqual(r.s['attempted'],before)
        self.assertEqual(r.s['team_config']['stage_key'],r.ticket['key'])

    def test_real_readers_complete_config_then_first_battle_dispatch_exactly_once(self):
        words=[('准备战斗',148,42),('故事队伍',84,120),('故事队伍',291,112),
               ('故事',699,217),('闯关成功',1259,233),('完成故事',1258,268),
               ('1名以上英雄存活',1300,301),('登场的敌人',1264,360),
               ('队伍战斗力',391,797),('管理队伍',89,851),('进行任务',1432,818),
               ('新关卡',1239,161),('8/100',1264,824)]
        def team(highlight=False):
            f=frame(words)
            if highlight:
                f.image[490:500,575:860]=(0,220,255)
                f.image[620:625,575:860]=(220,170,10)
            return f
        r=prepared_runner(team(True));before=copy.deepcopy(r.s['attempted']);snapshots=[]
        r.save.side_effect=lambda:snapshots.append(copy.deepcopy(r.s))
        self.assertEqual(tutorial_plan(r.frame)['rule'],'guided_owned_hero_slot')
        step(r);r.action.assert_called_once()
        r.frame=team(True);step(r)
        self.assertEqual(r.s['team_config']['phase'],'await_selector')
        self.assertNotIn(r.ticket['key'],r.s['attempted'])
        r.frame=team();step(r)  # A brief ordinary team frame cannot send entry.
        self.assertEqual(r.action.call_count,1);r.back.assert_not_called()
        r.frame=selector();step(r);r.frame=selector();step(r)
        self.assertEqual(r.s['team_config']['phase'],'await_position')
        self.assertEqual(r.action.call_count,2)
        r.frame=selector(True);step(r);r.frame=selector(True);step(r)
        self.assertEqual(r.s['team_config']['phase'],'completed')
        r.back.assert_called_once();self.assertEqual(r.action.call_count,2)
        self.assertEqual(r.s['attempted'],before)
        # The selector has actually gone, full original title/cost/layout return.
        r.frame=team();step(r)
        self.assertEqual(r.action.call_count,3);r.back.assert_called_once()
        self.assertEqual(r.s['active']['cost'],8)
        key=r.s['active']['key'];records=r.s['entry_dispatches'][key]
        self.assertEqual(len(records),1);self.assertEqual(records[0]['status'],'sent')
        self.assertTrue(any(s.get('entry_dispatches',{}).get(key,[{}])[-1].get('status')=='reserved' for s in snapshots))
        self.assertEqual(r.s['completed'],{});self.assertEqual(r.s['attempted']['old-failure'],before['old-failure'])
        original=copy.deepcopy(r.s['active'])
        self.assertTrue(step(r)[0])
        self.assertEqual(r.action.call_count,3);r.back.assert_called_once()
        self.assertTrue(all(r.s['active'].get(k)==v for k,v in original.items()));self.assertNotIn('unresolved_entries',r.s)

    def test_no_slot_chain_unknown_source_or_wrong_stage_never_assigns(self):
        for invalid in ('missing','source_unknown','wrong_stage','source_missing'):
            r,c=config_runner()
            if invalid!='missing':
                dispatch(c,'guided_owned_hero_slot');r.action.reset_mock()
                setup=r.s['team_config']
                if invalid=='source_unknown':setup['dispatches']['guided_owned_hero_slot']['status']='reserved'
                elif invalid=='source_missing':setup['dispatches']={}
                else:setup['stage_key']='another-stage'
            with self.assertRaises(TaskAttention):dispatch(c,'assign_owned_victoria')
            r.action.assert_not_called()

    def test_expired_slot_proof_and_existing_entry_never_start_setup(self):
        for invalid in ('expired','active'):
            r,c=config_runner()
            if invalid=='expired':r.ticket['verified_epoch']=time.time()-121
            else:r.s['active']=dict(r.ticket)
            with self.assertRaises(TaskAttention):dispatch(c,'guided_owned_hero_slot')
            r.action.assert_not_called();r.back.assert_not_called()

    def test_disk_error_unknown_send_and_not_sent_never_replay_setup(self):
        for failure in ('save','unknown','not_sent'):
            r,c=config_runner();dispatch(c,'guided_owned_hero_slot');r.action.reset_mock()
            if failure=='save':r.save.side_effect=OSError('disk full')
            else:r.action.side_effect=TapNotSent('cancelled') if failure=='not_sent' else RuntimeError('unknown')
            with self.assertRaises((OSError,RuntimeError,TapNotSent)):dispatch(c,'assign_owned_victoria')
            self.assertEqual(r.action.call_count,0 if failure=='save' else 1)
            original=copy.deepcopy(r.s);r.save.side_effect=None;r.action.side_effect=None;r.action.reset_mock()
            with self.assertRaises(TaskAttention):dispatch(TutorialController(r),'assign_owned_victoria')
            r.action.assert_not_called()
            self.assertEqual(r.s['team_config']['dispatches'],original['team_config']['dispatches'])

    def test_active_entry_is_not_archived_or_cancelled_on_plain_team(self):
        r=prepared_runner(preparation());r.s['active']=dict(r.ticket,cost=20)
        old=copy.deepcopy(r.s['active'])
        self.assertTrue(step(r)[0])
        self.assertTrue(all(r.s['active'].get(k)==v for k,v in old.items()));self.assertNotIn('unresolved_entries',r.s)
        r.action.assert_not_called();r.back.assert_not_called()

    def test_current_positive_placement_closes_selector_only_once(self):
        r,c=config_runner();dispatch(c,'guided_owned_hero_slot');dispatch(c,'assign_owned_victoria')
        r.action.reset_mock();f=selector(True);r.frame=f
        step(r);step(r);r.back.assert_called_once()
        r.frame=selector(True);step(r);r.back.assert_called_once();r.action.assert_not_called()
        self.assertEqual(r.s['team_config']['selector_close']['status'],'sent')
        r.frame=selector(True);step(r);r.back.assert_called_once()
        r.frame=selector(True);step(r);r.back.assert_called_once()

    def test_stale_or_one_sided_placement_does_not_close_selector(self):
        r,c=config_runner();dispatch(c,'guided_owned_hero_slot');dispatch(c,'assign_owned_victoria')
        r.action.reset_mock();r.frame=selector(True);r.frame.at=time.time()-5
        step(r);r.back.assert_not_called();r.action.assert_not_called()
        self.assertNotEqual(r.s['team_config']['phase'],'completed')

    def test_placed_result_with_missing_unknown_or_mismatched_source_never_closes(self):
        for invalid in ('id','source','stage'):
            r,c=config_runner();dispatch(c,'guided_owned_hero_slot');dispatch(c,'assign_owned_victoria')
            if invalid=='id':r.s['team_config'].pop('id')
            elif invalid=='source':r.s['team_config']['dispatches']['assign_owned_victoria']['status']='reserved'
            else:r.s['team_config']['stage_key']='other-stage'
            r.action.reset_mock();r.frame=selector(True)
            with self.assertRaises(TaskAttention):step(r)
            r.action.assert_not_called();r.back.assert_not_called()

    def test_back_send_unknown_is_never_repeated(self):
        r,c=config_runner();dispatch(c,'guided_owned_hero_slot');dispatch(c,'assign_owned_victoria')
        r.frame=selector(True)
        r.back.side_effect=RuntimeError('back unknown')
        with self.assertRaises(RuntimeError):step(r)
        self.assertEqual(r.s['team_config']['selector_close']['status'],'reserved')
        r.back.side_effect=None;r.back.reset_mock()
        r.frame=selector(True)
        with self.assertRaises(TaskAttention):step(r)
        r.back.assert_not_called()


class HighlightedSlotTests(unittest.TestCase):
    def current(self):
        words=[('准备战斗',148,42),('故事队伍',84,120),('故事队伍',291,112),('故事',699,217),
               ('闯关成功',1259,233),('完成故事',1258,268),('1名以上英雄存活',1300,301),
               ('登场的敌人',1264,360),('队伍战斗力',391,797),('管理队伍',89,851),('进行任务',1432,818),('新关卡',1239,161)]
        f=frame(words);cv=runner.cv2
        cv.ellipse(f.image,(562,652),(125,60),0,0,360,(0,230,255),12)
        cv.ellipse(f.image,(562,652),(135,69),0,0,360,(235,170,10),3)
        return f
    def test_neighbouring_blue_rims_do_not_hide_real_empty_bottom_slot(self):
        from tutorial_core import guided_team_slot_plan
        f=self.current()
        for x,y in ((515,410),(535,500),(565,550)):f.image[y:y+12,x:x+50]=(235,170,10)
        p=guided_team_slot_plan(f);self.assertIsNotNone(p);self.assertEqual((p['target']['x'],p['target']['y']),(562,652))
        self.assertEqual(team_entry_control(f)['kind'],'unknown')
    def test_red_and_large_blue_costumes_are_occupied_but_still_veto_underlying_entry(self):
        from tutorial_core import guided_team_slot_plan
        for color in ((0,0,230),(235,170,10)):
            f=self.current();f.image[400:500,530:600]=color
            self.assertIsNone(guided_team_slot_plan(f));self.assertEqual(team_entry_control(f)['kind'],'unknown')
    def test_real_runner_dispatches_configuration_not_entry_with_highlighted_empty_slot(self):
        r=prepared_runner(self.current());original=copy.deepcopy(r.s)
        step(r);r.action.assert_called_once();r.frame=self.current();step(r)
        self.assertEqual(r.action.call_count,1);self.assertIn('高亮空位',r.action.call_args.args[0])
        self.assertEqual(r.s['active'],None);self.assertEqual(r.s['attempted'],original['attempted'])
        self.assertNotIn('entry_dispatches',r.s)
        self.assertEqual(r.s['team_config']['phase'],'await_selector')
    def test_no_gold_no_blue_or_nonempty_core_never_authorizes_setup(self):
        from tutorial_core import guided_team_slot_plan
        f=self.current();f.image[640:665,540:590]=(0,0,230);self.assertIsNone(guided_team_slot_plan(f))
        for color in ((0,230,255),(235,170,10)):
            f=self.current();f.image[580:730,420:705]=22
            runner.cv2.ellipse(f.image,(562,652),(125,60),0,0,360,color,12)
            self.assertIsNone(guided_team_slot_plan(f))


class PrivateSelectorReplayTests(unittest.TestCase):
    def test_saved_incident_frames_never_authorize_entry_or_reassign_placed_hero(self):
        folder=Path(os.environ.get('EPIC7_TUTORIAL_TEAM_FIXTURES',str(Path(__file__).resolve().parents[1]/'.local/new-account-20261105/progress/evidence')))
        names=('000324-tutorial-assign_owned_victoria.png','001412-owned-hero-placed.png')
        if not all((folder/n).is_file() for n in names):self.skipTest('Private selector incident screenshots not distributed')
        ocr=runner.RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        for name,placed in zip(names,(False,True)):
            image=runner.cv2.imdecode(runner.np.frombuffer((folder/name).read_bytes(),runner.np.uint8),runner.cv2.IMREAD_COLOR)
            result,_=ocr(image);f=runner.Frame(image,result)
            self.assertTrue(owned_hero_selector_visible(f))
            self.assertEqual(team_entry_control(f)['kind'],'unknown')
            self.assertEqual(owned_hero_placement_verified(f),placed,name)
            if placed:
                self.assertEqual(runner.classify(f),'team_hero_selection')
                self.assertIsNone(owned_hero_assignment_plan(f))


if __name__=='__main__':unittest.main()
