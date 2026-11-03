"""Legacy story maps and success-only 3-7 repetition. No native input."""
import copy,json,os,sys,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
from story_core import StoryController,map_info,read_stage,exit_target,entry_cost,SAINT_STAGE
from task_blockers import TaskAttention
ROOT=Path(__file__).resolve().parents[1]
def fixture(name):
    folder=Path(os.environ.get('EPIC7_STORY_FIXTURES',str(ROOT/'.local/story-validation')))
    if not (folder/(name+'.png')).exists():raise unittest.SkipTest('Private legacy story fixture not distributed')
    raw=json.loads((folder/(name+'-ocr.json')).read_text(encoding='utf-8'))
    im=runner.cv2.imdecode(runner.np.frombuffer((folder/(name+'.png')).read_bytes(),runner.np.uint8),runner.cv2.IMREAD_COLOR)
    im=runner.cv2.resize(im,(1600,900))
    return runner.Frame(im,[(w['box'],w['text'],w['score']) for w in raw['words']])
def make(f):
    r=runner.Runner.__new__(runner.Runner);r.s={'attempted':{'old-mainline':{}},'completed':{'old-clear':{}},'active':None};r.frame=f
    r.evidence=Mock(return_value='private-evidence');r.save=Mock();r.action=Mock();r.back=Mock();r.drag=Mock()
    r.attention=Mock(side_effect=lambda c,t,x:(_ for _ in ()).throw(TaskAttention(c,t,x)))
    return r,StoryController(r,{'task':'saint_3_7'})
class LegacyScenes(unittest.TestCase):
    def test_map_selected_pin_matches_stage_1_4(self):
        f=fixture('live');p=map_info(f);self.assertEqual(p['selected']['id'],'1-4');self.assertEqual(runner.classify(f),'legacy_story_map')
    def test_partial_map_prefix_uses_unanimous_visible_chapter(self):
        f=fixture('map-after-1-6');page=map_info(f)
        self.assertEqual(page['selected']['id'],'1-6')
        row=next(r for r in page['rows'] if r['id']=='1-7');self.assertTrue(row['inferred_prefix'])
        r,s=make(f);s.bind(page['region']);s.book['last_cleared']='1-6'
        s.step(f,'legacy_story_map');self.assertIn('1-7',r.action.call_args.args[0])
    def test_conflicting_map_chapters_do_not_complete_partial_prefix(self):
        f=fixture('map-after-1-6')
        next(w for w in f.words if w['text'].startswith('1-8.'))['text']='2-8.铁之墓'
        self.assertNotIn('1-7',[r['id'] for r in map_info(f)['rows']])
    def test_map_tutorial_has_priority_over_underlying_map(self):
        f=fixture('map-tutorial');self.assertIsNotNone(map_info(f))
        self.assertEqual(runner.classify(f),'tutorial_skip')
    def test_quest_pin_is_not_required_for_exact_node_navigation(self):
        f=fixture('map-after-tutorial');r,s=make(f);s.bind('圣王国伊杰拉');s.book['last_cleared']='1-6'
        s.step(f,'legacy_story_map');self.assertIn('选择剧情节点 1-7',r.action.call_args.args[0])
        self.assertIn('xy',r.action.call_args.kwargs);self.assertLess(r.action.call_args.kwargs['xy'][1],200)
        s.step(f,'legacy_story_map');self.assertIn('打开剧情关卡准备页 1-7',r.action.call_args.args[0])
    def test_wrong_preparation_stage_never_enters(self):
        f=fixture('team');r,s=make(f);s.bind('圣王国伊杰拉');s.book['last_cleared']='1-6'
        s.step(f,'team');r.action.assert_not_called();r.back.assert_called_once();self.assertEqual(s.book['attempted'],{})
    def test_saint_mode_does_not_fall_back_to_episode(self):
        f=fixture('team');r,s=make(f)
        with self.assertRaises(TaskAttention):s.step(f,'lobby')
        r.action.assert_not_called()
    def test_defense_stage_uses_battle_start_without_changing_team(self):
        f=fixture('team-defense');self.assertEqual(runner.classify(f),'team');self.assertEqual(read_stage(f)['id'],'1-7')
        r,s=make(f);s.bind('圣王国伊杰拉');s.book['last_cleared']='1-6';s.step(f,'team')
        self.assertEqual(s.book['active']['stage'],'1-7');self.assertEqual(r.action.call_args.kwargs['word']['text'],'战斗开始')
    def test_offscreen_target_pans_without_guessing_an_entry(self):
        f=fixture('map-offscreen-1-9')
        r,s=make(f);s.bind('圣王国伊杰拉');s.book['last_cleared']='1-8';s.step(f,'legacy_story_map')
        r.drag.assert_called_once();r.action.assert_not_called();self.assertEqual(s.book['attempted'],{})
    def test_unlocked_region_exit_routes_to_real_next_chapter(self):
        f=fixture('region-exit-1');self.assertEqual(runner.classify(f),'legacy_story_map')
        r,s=make(f);s.bind('圣王国伊杰拉');s.book['last_cleared']='1-13'
        s.step(f,'legacy_story_map');self.assertIn('下一剧情地区 黎塔尼亚北部',r.action.call_args.args[0])
        self.assertEqual(s.desired_stage(),'2-1');self.assertEqual(s.book['last_cleared'],'1-13');self.assertEqual(s.book['attempted'],{})
    def test_three_region_cards_choose_goal_chapter_without_entry(self):
        f=fixture('region-cards');self.assertEqual(runner.classify(f),'legacy_story_regions')
        r,s=make(f);s.bind('圣王国伊杰拉');s.book.update(mode='farm',last_cleared='3-7')
        s.step(f,'legacy_story_regions');self.assertIn('黎塔尼亚北部',r.action.call_args.args[0]);self.assertEqual(s.book['attempted'],{})
    def test_region_route_override_expires_after_success_in_new_region(self):
        f=synthetic_team('2-1');r,s=make(f);s.bind('黎塔尼亚北部');s.book['last_cleared']='1-13'
        s.book['region_route']={'from_stage':'1-13','target_stage':'2-1'}
        s.enter(f,read_stage(f),f.find('进行任务'));s.clear('verified settlement')
        self.assertEqual(s.desired_stage(),'2-2');self.assertEqual(s.book['last_cleared'],'2-1')
    def test_second_region_native_exit_does_not_assume_final_shortcut_name(self):
        f=fixture('region-exit-2');r,s=make(f);s.bind('黎塔尼亚北部');s.book['last_cleared']='2-8'
        s.step(f,'legacy_story_map');self.assertIn('下一剧情地区',r.action.call_args.args[0]);self.assertEqual(s.desired_stage(),'3-1')
        self.assertNotIn('圣域最深处',r.action.call_args.args[0]);self.assertEqual(s.book['attempted'],{})
    def test_goal_farming_can_navigate_from_previous_region_without_new_entry(self):
        f=fixture('region-exit-2');r,s=make(f);s.bind('黎塔尼亚北部');s.book.update(mode='farm',last_cleared='3-7')
        s.book['region_transitions']=[{'target_stage':'3-1','region':'铎雪挪克特'}]
        s.step(f,'legacy_story_map');self.assertIn('返回目标 3-7',r.action.call_args.args[0]);self.assertEqual(s.book['attempted'],{});self.assertEqual(s.desired_stage(),'3-7')
    def test_preparation_banner_is_not_region_name(self):
        f=fixture('team-defense');self.assertEqual(read_stage(f)['region'],'圣王国伊杰拉')
    def test_support_and_team_keep_exact_stage_number(self):
        for name in ('prepare','team'):self.assertEqual(read_stage(fixture(name))['id'],'1-4')
        self.assertEqual(entry_cost(fixture('team')),(8,546))
    def test_blue_exit_is_navigation_not_repeat(self):
        f=fixture('legacy-exit');point=exit_target(f);self.assertGreaterEqual(point['dots'],5);self.assertGreater(point['x'],1500)
        self.assertEqual(runner.classify(f),'legacy_story_exit');r,s=make(f);s.bind('圣王国伊杰拉')
        s.book['active']={'id':'pending','stage':'1-4'}
        s.step(f,'legacy_story_exit');self.assertIn('蓝色出口',r.action.call_args.args[0]);self.assertIn('xy',r.action.call_args.kwargs)
    def test_clear_banner_exit_ignores_blue_stone_floor_fragments(self):
        f=fixture('clear-1-6');target=exit_target(f,clear_overlay=True)
        self.assertIsNotNone(target);self.assertGreaterEqual(target['dots'],5)
        self.assertGreater(target['x'],1500);self.assertEqual(runner.classify(f),'legacy_story_clear')
    def test_clear_banner_without_exit_has_no_navigation_target(self):
        f=fixture('clear-1-6');f.image[350:810,1000:1590]=0
        self.assertIsNone(exit_target(f,clear_overlay=True))
    def test_five_wave_defense_clear_dismisses_only_free_banner(self):
        f=fixture('clear-defense');self.assertEqual(runner.classify(f),'legacy_story_clear')
        self.assertIsNone(exit_target(f,clear_overlay=True));r,s=make(f);s.bind('圣王国伊杰拉')
        s.book['active']={'id':'d','stage':'1-7'};s.step(f,'legacy_story_clear')
        self.assertTrue(s.book['active']['victory_seen']);self.assertIn('关闭胜利遮罩',r.action.call_args.args[0]);self.assertEqual(s.book['completed'],{})
    def test_already_settled_blue_exit_leaves_instead_of_clicking_forever(self):
        f=fixture('exit-after-clear-3-6');self.assertEqual(runner.classify(f),'legacy_story_exit')
        r,s=make(f);s.bind('圣域最深处');s.book['last_cleared']='3-6'
        s.step(f,'legacy_story_exit');self.assertEqual(r.action.call_args.kwargs['word']['text'],'离开');self.assertEqual(s.book['completed'],{})
    def test_dark_or_missing_exit_path_never_uses_fixed_click(self):
        f=fixture('legacy-exit');f.image[:]=0;self.assertIsNone(exit_target(f))
    def test_entry_intent_is_saved_before_input(self):
        f=fixture('team');r,s=make(f);stage=read_stage(f);s.bind(stage['region'])
        def action(*a,**k):self.assertTrue(r.save.called);self.assertEqual(s.book['active']['stage'],'1-4');self.assertEqual(len(s.book['attempted']),1)
        r.action.side_effect=action;s.step(f,'team');self.assertEqual(r.s['attempted'],{'old-mainline':{}});self.assertEqual(r.s['completed'],{'old-clear':{}})
    def test_progress_cannot_repeat_cleared_non_target_stage(self):
        f=fixture('team');r,s=make(f);s.bind('圣王国伊杰拉');s.book['stages']['1-4']={};s.step(f,'team')
        r.action.assert_not_called();r.back.assert_called_once()
    def test_only_successful_target_clear_enables_farm(self):
        f=fixture('team');r,s=make(f);s.bind('圣王国伊杰拉');s.book['attempted']['a']={'id':'a','stage':'3-7'};s.book['active']={'id':'a','stage':'3-7'}
        s.clear('verified settlement');self.assertEqual(s.book['mode'],'farm');self.assertEqual(s.book['farm_runs'],1)
        self.assertIn('a',s.book['completed']);self.assertIn('a',s.book['attempted']);self.assertIsNone(s.book['active'])
    def test_unresolved_target_intent_is_never_repeated(self):
        f=fixture('team');r,s=make(f);s.bind('圣王国伊杰拉');s.book['attempted']['a']={'id':'a','stage':'3-7'}
        stage=dict(read_stage(f),id='3-7')
        with self.assertRaises(TaskAttention):s.enter(f,stage,f.find('进行任务'))
        r.action.assert_not_called()
    def test_cannot_enter_after_target_stage(self):
        f=fixture('team');r,s=make(f);s.bind('圣王国伊杰拉');stage=dict(read_stage(f),id='3-8')
        with self.assertRaises(TaskAttention):s.enter(f,stage,f.find('进行任务'))
        r.action.assert_not_called()
    def test_low_stamina_waits_without_recording_or_buying(self):
        f=fixture('team');r,s=make(f);s.bind('圣王国伊杰拉')
        with patch('story_core.entry_cost',return_value=(8,3)):keep,delay=s.enter(f,read_stage(f),f.find('进行任务'))
        self.assertTrue(keep);self.assertEqual(delay,30);self.assertEqual(s.book['attempted'],{});r.action.assert_not_called()


def synthetic_team(stage='3-7',stamina=50):
    rows=[]
    for text,x,y in [(stage+'.目标剧情',1230,165),('目标地区',1230,115),('进行任务',1450,825),('队伍战斗力',420,805),('AUTO',990,680),(f'8/{stamina}',1320,828)]:
        rows.append(([[x-30,y-10],[x+30,y-10],[x+30,y+10],[x-30,y+10]],text,.999))
    image=runner.np.full((900,1600,3),50,runner.np.uint8);image[650:710,900:1095]=(0,150,0)
    return runner.Frame(image,rows)

class StoryPolicyWithoutPrivateFiles(unittest.TestCase):
    def test_two_successful_target_entries_have_separate_auditable_records(self):
        f=synthetic_team();r,s=make(f);s.bind('目标地区')
        stage=read_stage(f)
        s.enter(f,stage,f.find('进行任务'));first=copy.deepcopy(s.book['active']);s.clear('first successful settlement')
        s.enter(f,stage,f.find('进行任务'));second=copy.deepcopy(s.book['active']);s.clear('second successful settlement')
        self.assertNotEqual(first['id'],second['id']);self.assertEqual(s.book['farm_runs'],2)
        self.assertEqual(len(s.book['attempted']),2);self.assertEqual(len(s.book['completed']),2)
        self.assertEqual(s.book['attempted'][first['id']],first);self.assertIsNone(s.book['active'])
        self.assertEqual(r.s['attempted'],{'old-mainline':{}})
    def test_unresolved_entry_is_preserved_across_controller_restart(self):
        f=synthetic_team();r,s=make(f);s.bind('目标地区');s.enter(f,read_stage(f),f.find('进行任务'));before=copy.deepcopy(s.book)
        restored=StoryController(r,{'task':'saint_3_7'})
        with self.assertRaises(TaskAttention):restored.enter(f,read_stage(f),f.find('进行任务'))
        self.assertEqual(restored.book,before)
    def test_general_story_restores_current_namespace(self):
        f=synthetic_team('1-4');r,s=make(f);s=StoryController(r,{'task':'mainline'});s.bind('目标地区')
        s.enter(f,read_stage(f),f.find('进行任务'));restored=StoryController(r,{'task':'mainline'})
        self.assertTrue(restored.context);self.assertEqual(restored.book_id,'legacy|目标地区');self.assertEqual(restored.book['active']['stage'],'1-4')
    def test_resource_wait_is_not_accelerated_by_fast_mode(self):
        from task_timing import next_delay
        f=synthetic_team(stamina=3);r,s=make(f);s.bind('目标地区')
        keep,delay=s.enter(f,read_stage(f),f.find('进行任务'));self.assertTrue(keep)
        self.assertEqual(next_delay('natural_resource_wait',delay),30);r.action.assert_not_called()
    def test_preparing_3_8_after_goal_never_spends_stamina(self):
        f=synthetic_team('3-8');r,s=make(f);s.bind('目标地区');s.book.update(mode='farm',last_cleared='3-7',farm_runs=2)
        s.enter(f,read_stage(f),f.find('进行任务'));r.action.assert_not_called();r.back.assert_called_once();self.assertEqual(s.book['attempted'],{})
    def test_defeat_and_purchase_veto_precede_any_story_action(self):
        f=synthetic_team()
        for text,expected in [('天空石购买体力','resource_stop'),('装备已满','capacity_stop'),('战斗失败','defeat')]:
            with self.subTest(text=text):
                other=copy.deepcopy(f);other.words.append(dict(text=text,x=800,y=400,score=.999));other.text+='\n'+text;other.clean=runner.norm(other.text)
                self.assertEqual(runner.classify(other),expected)

    def test_switching_to_general_story_does_not_trap_it_in_farming(self):
        f=synthetic_team();r,s=make(f);s.bind('目标地区');s.book.update(mode='farm',last_cleared='3-7');s.book['stages']['3-7']={'success':True}
        restored=StoryController(r,{'task':'mainline'})
        self.assertEqual(restored.desired_stage(),'3-8');self.assertEqual(restored.book['mode'],'progress');self.assertIn('3-7',restored.book['stages'])
    def test_selecting_saint_after_other_story_progress_returns_to_cleared_target(self):
        f=synthetic_team();r,s=make(f);s.bind('目标地区');s.book.update(mode='progress',last_cleared='3-9');s.book['stages']['3-7']={'success':True}
        restored=StoryController(r,{'task':'saint_3_7'})
        self.assertEqual(restored.desired_stage(),'3-7');self.assertEqual(restored.book['mode'],'farm')
