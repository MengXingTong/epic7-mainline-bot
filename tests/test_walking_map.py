"""Synthetic shared walking-map/mainline regressions; no live client or account data."""
import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch

import runner
from story_core import StoryController,walking_map_info,team_entry_control,SAINT_BOOK
from walking_map import node_key
from task_blockers import TaskAttention
from pc_backend import FrameExpired,NavigationFrameExpired,PcSafetyError,InputDeliveryError
from test_unknown_scene_diagnostics import OVERVIEW,overview
from test_story_only_nodes import fake_runner
from test_preparation_auto_independence import legacy_story
from test_stall_recovery import frame


def map_frame(region='示例地区',coloured=(1,)):
    f=overview([('示例地区' if t=='示例地区' else t,x,y) for t,x,y in OVERVIEW])
    f.words[0]['text']=region
    for number,x,y in ((1,321,523),(2,802,445),(3,1240,636)):
        runner.cv2.circle(f.image,(x,y-65),23,(30,170,240) if number in coloured else (70,70,70),-1)
    return f


def prep(region='示例地区',number=1,name='银杉森林',full=True,cost='8/100',support=False):
    label=('12-' if full else '')+str(number)+'.'+name
    if support:
        return frame([('准备战斗',148,42),('选择辅助英雄',300,120),('选择队伍',1400,825),
                      (region,1242,116),(label,1245,166)])
    f=legacy_story()
    for w in f.words:
        if w['text']=='目标地区':w['text']=region
        elif w['text']=='1-4.目标剧情':w['text']=label
        elif w['text']=='8/100':w['text']=cost
    return f


class WalkingMapTests(unittest.TestCase):
    def make(self,f=None):
        r=fake_runner(f or map_frame());r.run_id='same-run';r.pc=None;r.adb=Mock();r.drag=Mock();r.cfg.update(serial='synthetic-instance',package='synthetic-game')
        r.s.update(last_cleared={'key':'original-clear'},entry_dispatches={'original':[{'status':'sent'}]},
                   attempted={'old-failure':{'name':'保留旧失败','outcome':'defeat'}},completed={'old-clear':{'proof':'original'}})
        r.attention=Mock(side_effect=lambda c,t,x:(_ for _ in ()).throw(TaskAttention(c,t,x)))
        s=StoryController(r,dict(task='mainline'));r.story=s
        return r,s
    def apply(self,r,s,f,mode=None):
        r.frame=f
        return s.step(f,mode or runner.classify(f))
    def opened(self):
        r,s=self.make();self.apply(r,s,r.frame);return r,s
    def enter(self,r,s,**kwargs):
        return self.apply(r,s,prep(**kwargs),'team')

    def test_short_maps_share_existing_scene_and_never_invent_episode_or_chapter(self):
        for region in ('示例地区','另一大陆','第十地区'):
            f=map_frame(region);p=walking_map_info(f)
            self.assertEqual(runner.classify(f),'legacy_story_map')
            self.assertEqual(p['region'],region);self.assertIsNone(p['chapter'])
            self.assertTrue(all(r['id'] is None for r in p['rows']))
            self.assertFalse(any(r.get('completion')=='completed' for r in p['rows']))
    def test_all_visible_node_lock_observations_and_positive_navigation_are_separate(self):
        p=walking_map_info(map_frame())
        self.assertEqual([r['navigation_visible'] for r in p['rows']],[True,False,False])
        self.assertTrue(all('lock_score' in r and 'locked' in r for r in p['rows']))
        self.assertTrue(all(r['completion']=='unconfirmed' for r in p['rows']))
    def test_closed_lock_overrides_coloured_native_node(self):
        f=map_frame(coloured=(1,2,3));row=walking_map_info(f)['rows'][1]
        path=Path(runner.__file__).parent/'assets/lock.png'
        lock=runner.cv2.imdecode(runner.np.frombuffer(path.read_bytes(),runner.np.uint8),0)
        h,w=lock.shape;x,y=round(row['word']['x']),round(row['word']['y']-65)
        f.image[y-h//2:y-h//2+h,x-w//2:x-w//2+w]=runner.cv2.cvtColor(lock,runner.cv2.COLOR_GRAY2BGR)
        read=walking_map_info(f)['rows'][1]
        self.assertTrue(read['locked']);self.assertFalse(read['navigation_visible'])
    def test_incomplete_weak_duplicate_or_displaced_shell_never_identifies_map(self):
        for index in (0,1,2,6,7,8):
            for mode in ('missing','weak','duplicate','move'):
                f=map_frame()
                if mode=='missing':f.words.pop(index)
                elif mode=='weak':f.words[index]['score']=.89
                elif mode=='duplicate':f.words.append(copy.deepcopy(f.words[index]))
                else:f.words[index]['x']=600;f.words[index]['y']=100
                self.assertIsNone(walking_map_info(f),(index,mode))
    def test_uncertain_or_ambiguous_node_cannot_disappear_from_checks(self):
        f=map_frame();f.words[4]['score']=.979;self.assertIsNone(walking_map_info(f))
        f=map_frame();f.words[4]['text']='1.另一个同编号节点';self.assertIsNone(walking_map_info(f))
    def test_free_map_open_persists_source_and_intent_without_reserving_entry(self):
        r,s=self.make();original=copy.deepcopy(r.s);snapshots=[]
        r.action.side_effect=lambda *a,**k:snapshots.append(copy.deepcopy(r.s))
        self.apply(r,s,r.frame)
        self.assertEqual(r.action.call_count,1);self.assertEqual(r.action.call_args.kwargs['word']['text'],'准备战斗')
        self.assertEqual(snapshots[0]['story_progress']['books'][s.book_id]['walking_map']['navigation'][0]['status'],'reserved')
        self.assertEqual(s.book['walking_map']['navigation'][0]['status'],'sent')
        self.assertEqual(s.book['attempted'],{})
        for key in ('attempted','completed','last_cleared','entry_dispatches'):self.assertEqual(r.s[key],original[key])
    def test_full_or_short_preparation_number_binds_observed_map_not_episode(self):
        for full in (False,True):
            r,s=self.opened();self.enter(r,s,full=full)
            a=s.book['active'];self.assertEqual(a['stage'],node_key('示例地区',1));self.assertEqual(a['cost'],8)
            self.assertEqual(len(s.book['attempted']),1);self.assertEqual(len(s.book['entry_dispatches']),1)
            self.assertEqual(a['map_binding']['region'],'示例地区');self.assertEqual(s.book['completed'],{})
            self.assertEqual(r.action.call_args.kwargs['word']['text'],'进行任务')
    def test_support_and_team_share_original_entry_engine_without_auto_gate(self):
        r,s=self.opened();self.apply(r,s,prep(support=True),'support')
        self.assertEqual(r.action.call_args.kwargs['word']['text'],'选择队伍')
        self.enter(r,s);self.assertEqual(len(s.book['attempted']),1)
        self.assertEqual(s.book['active']['team_entry_mode'],'single_task')
        for variant in ('weak','duplicate','overlay'):
            r,s=self.opened();f=prep(support=True)
            target=next(w for w in f.words if w['text']=='选择队伍')
            if variant=='weak':target['score']=.97
            elif variant=='duplicate':f.words.append(copy.deepcopy(target))
            else:f=frame([(w['text'],w['x'],w['y']) for w in f.words]+[('购买体力',800,450)])
            count=r.action.call_count;self.apply(r,s,f,'support')
            self.assertEqual(r.action.call_count,count);self.assertEqual(s.book['attempted'],{})
    def test_current_preparation_must_match_map_region_number_and_name(self):
        for kwargs in (dict(region='别的地区'),dict(number=9),dict(name='别的森林')):
            r,s=self.opened();count=r.action.call_count;self.enter(r,s,**kwargs)
            self.assertEqual(s.book['attempted'],{});self.assertEqual(r.action.call_count,count)
    def test_missing_or_weak_preparation_fields_observe_without_entry_or_manual_latch(self):
        for index in (-3,-2):
            r,s=self.opened();f=prep();f.words[index]['score']=.97
            self.apply(r,s,f,'team');self.assertEqual(s.book['attempted'],{})
            self.assertEqual(r.action.call_count,1);r.attention.assert_not_called()
    def test_stale_preparation_source_from_other_run_returns_known_page_not_entry(self):
        r,s=self.opened();r.run_id='new-run';self.enter(r,s)
        r.back.assert_called_once();self.assertEqual(s.book['attempted'],{})
    def test_unknown_preparation_never_authorizes_native_back(self):
        r,s=self.opened();r.run_id='new-run'
        self.apply(r,s,frame([('进行任务',1438,825)]),'team')
        r.back.assert_not_called();self.assertEqual(s.book['attempted'],{})
    def test_geometry_mismatch_raises_safety_error_not_freshness_retry(self):
        r,s=self.opened();f=prep();f.raw_size=(1280,720)
        with self.assertRaises(PcSafetyError):self.apply(r,s,f,'team')
        self.assertEqual(s.book['attempted'],{})
    def test_sent_resource_entry_is_never_reissued_on_wait_or_map_return(self):
        r,s=self.opened();self.enter(r,s);count=r.action.call_count;original=copy.deepcopy(s.book['attempted'])
        self.enter(r,s);self.apply(r,s,map_frame())
        self.assertEqual(r.action.call_count,count);self.assertEqual(s.book['attempted'],original)
        self.assertEqual(s.book['completed'],{});r.attention.assert_not_called()
    def test_independent_settlement_clears_then_progresses_visible_next_node(self):
        r,s=self.opened();self.enter(r,s);first=copy.deepcopy(s.book['active'])
        result=frame([('获得的道具',1453,60),('战斗结果',1260,825),('确认',1442,825)])
        self.assertEqual(runner.classify(result),'settlement');self.apply(r,s,result)
        self.assertIn(first['id'],s.book['completed']);self.assertEqual(s.book['last_cleared'],first['stage'])
        self.apply(r,s,map_frame(coloured=(1,2)))
        self.assertIn('选择行走地图节点 2',r.action.call_args.args[0]);self.assertEqual(len(s.book['attempted']),1)
        self.apply(r,s,map_frame(coloured=(1,2)))
        self.assertEqual(r.action.call_args.kwargs['word']['text'],'准备战斗')
        self.enter(r,s,number=2,name='清泉溪谷');self.assertEqual(len(s.book['attempted']),2)
        self.assertEqual(len(s.book['completed']),1)
    def test_locked_next_node_never_becomes_input_or_completion_from_colours(self):
        r,s=self.opened();self.enter(r,s);s.clear('synthetic independent settlement');count=r.action.call_count
        f=map_frame(coloured=(1,));row=walking_map_info(f)['rows'][1]
        lock=runner.cv2.imdecode(runner.np.frombuffer((Path(runner.__file__).parent/'assets/lock.png').read_bytes(),runner.np.uint8),0)
        h,w=lock.shape;x,y=map(round,row['node_target'])
        f.image[y-h//2:y-h//2+h,x-w//2:x-w//2+w]=runner.cv2.cvtColor(lock,runner.cv2.COLOR_GRAY2BGR)
        self.apply(r,s,f)
        self.assertEqual(r.action.call_count,count);self.assertEqual(len(s.book['attempted']),1)
    def test_colour_and_quest_pin_do_not_write_completion(self):
        r,s=self.opened();self.apply(r,s,map_frame(coloured=(1,2,3)))
        self.assertEqual(s.book['completed'],{});self.assertEqual(s.book['stages'],{})
    def test_region_identity_and_same_number_branches_are_independent(self):
        r,s=self.opened();one=s.book_id
        r.current_screen_start=True;s=StoryController(r,dict(task='mainline'));r.story=s
        self.apply(r,s,map_frame('分支地区'));two=s.book_id
        self.assertNotEqual(one,two);self.assertNotEqual(node_key('示例地区',1),node_key('分支地区',1))
        self.assertIn(one,r.s['story_progress']['books'])
    def test_existing_matching_history_reused_not_replaced_with_blank_book(self):
        r,s=self.opened();bid=s.book_id;self.enter(r,s)
        original=copy.deepcopy(s.book['attempted']);replacement=StoryController(r,dict(task='mainline'))
        self.apply(r,replacement,map_frame());self.assertEqual(replacement.book_id,bid)
        self.assertEqual(replacement.book['attempted'],original)
        # Explicit new Start archives, never retries or falsifies the old result.
        old_active=copy.deepcopy(replacement.book['active'])
        r.run_id='explicit-new-run';r.current_screen_start=True
        restarted=StoryController(r,dict(task='mainline'))
        self.assertIsNone(restarted.book['active'])
        self.assertEqual(restarted.book['unresolved_entries'][-1]['entry'],old_active)
        self.assertEqual(restarted.book['attempted'],original)
        self.assertEqual(restarted.book['completed'],{})
        self.apply(r,restarted,map_frame());count=r.action.call_count
        with self.assertRaises(TaskAttention):self.enter(r,restarted)
        self.assertEqual(r.action.call_count,count)
        self.assertEqual(restarted.book['attempted'],original)
    def test_conflicting_node_name_cannot_overwrite_original_binding(self):
        r,s=self.opened();old=copy.deepcopy(s.book['walking_map']['regions']);f=map_frame();f.words[3]['text']='1.改名节点'
        with self.assertRaises(TaskAttention):self.apply(r,s,f)
        self.assertEqual(s.book['walking_map']['regions'],old)
    def test_old_legacy_and_numbered_mainline_history_block_alias_reentry(self):
        for mode in ('legacy','mainline'):
            r,s=self.opened();entry=dict(stage='12-1',region='示例地区',name='银杉森林')
            if mode=='legacy':s.book['attempted']['old-dispatch']=entry
            else:r.s['attempted']['old-key']=entry
            count=r.action.call_count;self.enter(r,s)
            self.assertEqual(r.action.call_count,count);self.assertIsNone(s.book['active'])
    def test_no_saint_repetition_permission_leaks_into_mainline_walking_map(self):
        r,s=self.make();saint=StoryController(r,dict(task='saint_3_7'))
        with self.assertRaises(TaskAttention):self.apply(r,saint,map_frame())
        self.assertEqual(saint.book_id,SAINT_BOOK);r.action.assert_not_called()
    def test_critical_record_failure_prevents_all_input(self):
        r,s=self.make();r.save.side_effect=OSError('critical write failure')
        with self.assertRaises(OSError):self.apply(r,s,r.frame)
        r.action.assert_not_called();r.adb.assert_not_called()
    def test_free_navigation_expiry_recaptures_but_unknown_send_does_not_reuse_intent(self):
        r,s=self.make();r.action.side_effect=FrameExpired('before press')
        with self.assertRaises(NavigationFrameExpired):self.apply(r,s,r.frame)
        self.assertEqual(s.book['walking_map']['navigation'][-1]['status'],'not_sent')
        r.action.side_effect=InputDeliveryError('uncertain')
        with self.assertRaises(InputDeliveryError):self.apply(r,s,map_frame())
        record=copy.deepcopy(s.book['walking_map']['navigation'][-1]);count=r.action.call_count
        self.apply(r,s,map_frame());self.assertEqual(r.action.call_count,count)
        self.assertEqual(s.book['walking_map']['navigation'][-1],record)
    def test_source_age_does_not_get_refreshed_to_authorize_navigation(self):
        r,s=self.make();r.frame.at=time.time()-10
        self.apply(r,s,r.frame);r.action.assert_not_called();self.assertEqual(s.book['walking_map']['navigation'],[])
    def test_single_visible_node_still_uses_layout_without_inventing_chapter(self):
        f=map_frame();f.words=[w for w in f.words if not w['text'].startswith(('2.','3.'))]
        page=walking_map_info(f)
        self.assertEqual(len(page['rows']),1);self.assertIsNone(page['chapter'])
        self.assertIsNone(page['rows'][0]['id'])
    def test_missing_next_node_reuses_bounded_background_pan_not_resource_input(self):
        r,s=self.opened();self.enter(r,s);s.clear('synthetic independent settlement')
        f=map_frame();f.words=[w for w in f.words if not w['text'].startswith('2.')]
        count=r.action.call_count;self.apply(r,s,f)
        r.drag.assert_called_once();self.assertEqual(r.action.call_count,count)
        self.assertEqual(len(s.book['attempted']),1)
    def test_native_region_route_preserves_book_without_guessing_next_chapter(self):
        r,s=self.opened();self.enter(r,s,number=3,name='高地草原');s.clear('synthetic independent settlement')
        original_book=s.book_id;old=copy.deepcopy(s.book['completed']);f=map_frame()
        f.words+=frame([('往另一地区',800,300)]).words
        runner.cv2.rectangle(f.image,(760,205),(840,255),(0,180,0),-1)
        self.apply(r,s,f);self.assertIn('前往已解锁行走地区',r.action.call_args.args[0])
        route=copy.deepcopy(s.book['walking_map']['route']);self.assertNotIn('target_stage',route)
        self.apply(r,s,map_frame('另一地区'))
        self.assertEqual(s.book_id,original_book);self.assertEqual(s.book['completed'],old)
        self.assertEqual(s.book['walking_map']['route']['status'],'observed')
        self.enter(r,s,region='另一地区')
        self.assertEqual(s.book['active']['stage'],node_key('另一地区',1))
        self.assertNotEqual(s.book['active']['stage'],node_key('示例地区',1))
    def test_ambiguous_old_region_buckets_stop_without_new_blank_history(self):
        r,s=self.opened();s.book['attempted']['keep']={'stage':'keep','name':'保留'}
        r.s['story_progress']['books']['duplicate']=copy.deepcopy(s.book)
        original=copy.deepcopy(r.s['story_progress']['books'])
        with self.assertRaises(TaskAttention):self.apply(r,s,map_frame())
        self.assertEqual(r.s['story_progress']['books'],original)
    def test_target_rebinding_and_tampered_map_source_never_authorize_entry(self):
        r,s=self.opened();r.cfg['serial']='another-instance'
        with self.assertRaises(PcSafetyError):self.enter(r,s)
        self.assertEqual(s.book['attempted'],{})
        r,s=self.opened();s.book['walking_map']['preparation_source']['rows'][0]['name']='另一个名字'
        self.enter(r,s,name='另一个名字')
        self.assertEqual(s.book['attempted'],{});self.assertEqual(r.action.call_count,1)
    def test_stage_names_do_not_lose_chinese_one_or_meaningful_characters(self):
        from walking_map import text_key
        self.assertNotEqual(text_key('第一森林'),text_key('第森林'))
    def test_whitespace_variant_reuses_region_history_not_a_blank_bucket(self):
        r,s=self.opened();bid=s.book_id;old=copy.deepcopy(s.book['attempted'])
        self.apply(r,s,map_frame('示 例地区'))
        self.assertEqual(s.book_id,bid);self.assertEqual(s.book['attempted'],old)
    def test_shared_walking_entry_is_scheduled_before_full_screen_stability_wait(self):
        from task_timing import needs_stability_wait
        self.assertFalse(needs_stability_wait(runner.classify(map_frame())))

    def test_zero_cost_walking_entry_is_recorded_once_without_purchase_or_replay(self):
        r,s=self.opened();self.enter(r,s,cost='0/100')
        self.assertEqual(s.book['active']['cost'],0);count=r.action.call_count
        self.enter(r,s,cost='0/100');self.assertEqual(r.action.call_count,count)
        self.assertEqual(s.book['completed'],{})
    def test_full_legacy_number_reader_has_no_chapter_nine_hard_limit(self):
        from story_core import stage_id
        self.assertEqual(stage_id('12-101.另一章节点'),'12-101')
        self.assertIsNone(stage_id('1234-1.不完整编号'))
        self.assertIsNone(stage_id('12-1234.不完整编号'))

    def test_capacity_paid_defeat_and_unknown_modal_still_outrank_map(self):
        base=[(w['text'],w['x'],w['y']) for w in map_frame().words]
        for text,scene in [('装备背包已满','capacity_stop'),('购买体力','resource_stop'),('战斗失败','defeat'),('确认','unknown_dialog')]:
            self.assertEqual(runner.classify(frame(base+[(text,800,450)])),scene)


if __name__=='__main__':unittest.main()
