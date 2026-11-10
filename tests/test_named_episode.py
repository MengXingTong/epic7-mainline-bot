"""Named Episode maps are mainline, with independent persistent identity."""
import copy
import time
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import runner
from map_identity import (named_episode,episode_identity,stage_key,stage_order,
    same_chapter,valid_stage_identity,episode_handoff,native_forward_chapter)
from progression_facts import map_progress_fact
from test_map_layout import map_frame,frame,fake_runner


def named_map(title='亚奇',story=True):
    f=map_frame()
    f.words[0]['text']='外传Episode：'+title
    f.words[1]['text']='第1章精灵王的契约者'
    f.words[2]['text']='1.黑狼与少女'
    f.words[3]['text']='2.精灵王的契约者'
    f.words[4]['text']='观看故事' if story else '准备战斗'
    return f


def read_map(f):return runner.Runner.__new__(runner.Runner).map_ticket(f)


class NamedEpisodeIdentityTests(unittest.TestCase):
    def test_named_header_uses_same_map_control_and_explicit_independent_identity(self):
        f=named_map();self.assertEqual(runner.classify(f),'map')
        d,rows,proof=read_map(f)
        self.assertEqual(d['episode'],'named:亚奇')
        self.assertEqual((d['chapter'],d['stage'],d['name']),(1,1,'黑狼与少女'))
        self.assertEqual(d['key'],stage_key(d))
        self.assertTrue(d['key'].startswith('EN-'))
        self.assertEqual(proof,'未通关蓝色当前节点')
        self.assertEqual(runner.mainline_map_control(f)['kind'],'story_only')
        self.assertEqual(len(rows),2)

    def test_battle_map_reuses_original_preparation_contract(self):
        f=named_map(story=False);r=fake_runner(f)
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-named-test')):
            r.step(f)
        r.action.assert_called_once()
        self.assertEqual(r.action.call_args.args[0],'未通关验证通过，准备战斗')
        self.assertEqual(r.ticket['episode'],'named:亚奇')
        self.assertFalse(r.s['attempted'])

    def test_not_a_title_whitelist_and_historic_keys_remain_byte_identical(self):
        keys=set()
        for title in ('亚奇','另一个世界','A New Journey','编号 6'):
            f=named_map(title);d,_,_=read_map(f);keys.add(d['key'])
            self.assertEqual(runner.classify(f),'map')
        self.assertEqual(len(keys),4)
        self.assertEqual(stage_key(dict(episode=5,chapter=10,chapter_suffix='S',stage=8)),'E5-C10S-S8')
        self.assertNotIn('E1-C1-S1',keys)

    def test_named_scopes_branches_and_numbered_maps_do_not_alias(self):
        base=dict(episode=named_episode('亚奇'),chapter=1,stage=1)
        values=[base,dict(base,episode=named_episode('另一名称')),dict(base,episode=1),dict(base,chapter_suffix='S')]
        self.assertEqual(len({stage_key(d) for d in values}),4)
        self.assertTrue(all(not same_chapter(base,d) for d in values[1:]))
        self.assertLess(stage_order(base),stage_order(dict(base,stage=2)))
        self.assertLess(stage_order(base),stage_order(dict(base,chapter_suffix='S')))

    def test_header_normalizes_width_and_spacing_without_reading_account_fields(self):
        for title in ('外传Episode：亚奇','外传 Episode : 亚奇','外传Ｅｐｉｓｏｄｅ：亚奇'):
            f=named_map();f.words[0]['text']=title
            self.assertEqual(runner.mainline_episode(f)['episode'],'named:亚奇')
        self.assertEqual(named_episode(' A   New Journey '),'named:a new journey')

    def test_background_motion_does_not_send_a_known_named_map_to_stability_fallback(self):
        from task_timing import needs_stability_wait
        f=named_map()
        self.assertFalse(needs_stability_wait(runner.classify(f)))
        f.image[200:650,600:1000]=(240,40,90)
        self.assertEqual(runner.classify(f),'map')
        self.assertFalse(needs_stability_wait(runner.classify(f)))

    def test_named_identity_survives_json_and_normalizes_latin_case(self):
        import json
        f=named_map('A New Journey');d,_,_=read_map(f)
        restored=json.loads(json.dumps(d))
        self.assertEqual(stage_key(restored),d['key'])
        other=named_map('a new journey');self.assertEqual(read_map(other)[0]['key'],d['key'])

    def test_weak_moved_missing_or_duplicate_identity_never_authorizes_map(self):
        for condition in ('weak','moved','missing_title','duplicate_named','duplicate_numbered','unknown_prefix'):
            with self.subTest(condition=condition):
                f=named_map()
                if condition=='weak':f.words[0]['score']=.979
                elif condition=='moved':f.words[0]['y']=160
                elif condition=='missing_title':f.words[0]['text']='外传Episode：'
                elif condition=='duplicate_named':f.words.append(copy.deepcopy(f.words[0]))
                elif condition=='duplicate_numbered':f.words+=frame([('Episode 6',200,44)]).words
                else:f.words[0]['text']='活动Episode：亚奇'
                self.assertIsNone(runner.mainline_episode(f))
                self.assertIsNone(runner.mainline_map_control(f))

    def test_weak_named_identity_cannot_expose_another_underlying_numbered_header(self):
        f=named_map();f.words[0]['score']=.97
        f.words+=frame([('Episode 6',200,44)]).words
        self.assertIsNone(runner.mainline_episode(f))

    def test_resources_capacity_defeat_and_unknown_dialog_still_outrank_named_maps(self):
        for words,expected in [([('装备背包已满',800,440)],'capacity_stop'),
                               ([('行动力不足',800,440)],'resource_stop'),
                               ([('FAILED',800,250)],'defeat'),
                               ([('确认',900,575),('取消',650,575)],'unknown_dialog')]:
            f=named_map();f.words+=frame(words).words
            self.assertEqual(runner.classify(f),expected)

    def test_invalid_episode_identity_is_not_guessed_or_coerced(self):
        for ep in (None,True,0,-1,'1','named:','named: 亚奇','named:A/B'):
            with self.subTest(ep=ep):
                d=dict(episode=ep,chapter=1,stage=1)
                self.assertFalse(valid_stage_identity(d))
                with self.assertRaises(ValueError):stage_key(d)
                self.assertFalse(same_chapter(d,d))

    def test_same_named_episode_native_chapter_handoff_not_a_cross_title_match(self):
        old=dict(episode=named_episode('亚奇'),chapter=1,stage=8)
        self.assertTrue(native_forward_chapter(old,dict(old,chapter=2,stage=1)))
        self.assertFalse(native_forward_chapter(old,dict(old,episode=named_episode('另一个'),chapter=2,stage=1)))


class NamedEpisodeProgressionTests(unittest.TestCase):
    def fixture(self):
        f=named_map();d,rows,_=read_map(f)
        entry=copy.deepcopy(d);entry.update(entry_kind='story_only',cost=0,start_epoch=time.time()-30)
        return f,d,rows,entry

    def run_step(self,r):
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-named-test')),patch('story_open_ack.register_open'):
            return r.step(r.frame)

    def test_unified_unknown_narration_never_falls_back_to_cg_click_or_hold(self):
        f=frame();r=fake_runner(f);r.run_id='unified';r.last_mode='unknown';r.mode_since=time.time()-500
        r.battle_seen=0;r.last_gesture=0;r.adb=Mock()
        r.s['active']=dict(key='original',cost=0,entry_kind='story_only')
        self.assertTrue(self.run_step(r)[0]);r.action.assert_not_called();r.adb.assert_not_called()
        self.assertEqual(r.unknown_gestures,0)
        self.assertEqual(r.observation_wait['code'],'unknown_scene')

    def test_current_clear_only_completes_the_same_named_scope(self):
        f,d,rows,entry=self.fixture();rows[0].update(completion='cleared',clear_badge=True)
        self.assertTrue(map_progress_fact(f,entry,d,rows).completed)
        entry['episode']=named_episode('另一个')
        self.assertFalse(map_progress_fact(f,entry,d,rows).completed)

    def test_original_locked_successor_now_unlocked_completes_current_named_stage(self):
        f,d,rows,entry=self.fixture();entry['progress_before']=dict(key=entry['key'],next_locked=True)
        rows[1].update(locked=False,lock_score=.1)
        fact=map_progress_fact(f,entry,d,rows)
        self.assertTrue(fact.completed);self.assertEqual(fact.proof['source'],'successor_lock_to_unlock')

    def test_episode_handoff_archives_old_active_without_fabricating_a_clear(self):
        f,d,rows,_=self.fixture();r=fake_runner(f)
        old=dict(episode=5,chapter=10,chapter_suffix='S',stage=8,key='E5-C10S-S8',name='old story',entry_kind='story_only',cost=0,start_epoch=time.time()-30)
        r.s.update(active=copy.deepcopy(old),attempted={old['key']:copy.deepcopy(old)},entry_dispatches={old['key']:[dict(status='sent',keep='original')]},last_cleared=dict(episode=5,chapter=10,stage=7))
        previous=copy.deepcopy(r.s)
        self.assertTrue(self.run_step(r)[0])
        self.assertEqual(r.s['unresolved_entries'][-1]['entry']['key'],old['key'])
        archived=r.s['unresolved_entries'][-1]['entry']
        for key,value in old.items():self.assertEqual(archived[key],value)
        self.assertEqual(r.s['attempted'][old['key']],previous['attempted'][old['key']])
        self.assertEqual(r.s['entry_dispatches'][old['key']],previous['entry_dispatches'][old['key']])
        self.assertEqual(r.s['completed'],{})
        self.assertEqual(r.s['last_cleared'],previous['last_cleared'])
        self.assertEqual(r.s['active']['episode'],'named:亚奇')
        self.assertEqual(r.s['active']['key'],d['key'])
        r.action.assert_called_once()
        self.assertEqual(r.action.call_args.args[0],'观看故事（仅一次）')

    def test_old_numbered_node_same_chapter_stage_does_not_block_distinct_named_node(self):
        f,d,_,_=self.fixture();r=fake_runner(f)
        r.s['attempted']['E1-C1-S1']=dict(key='E1-C1-S1')
        r.s['completed']['E1-C1-S1']=dict(key='E1-C1-S1',proof='original')
        self.assertTrue(self.run_step(r)[0]);r.action.assert_called_once()
        self.assertIn(d['key'],r.s['attempted'])
        self.assertEqual(r.s['completed']['E1-C1-S1']['proof'],'original')

    def test_named_attempt_or_completed_history_never_reopens(self):
        for recorded in ('attempted','completed'):
            f,d,_,entry=self.fixture();r=fake_runner(f);r.s[recorded][d['key']]=copy.deepcopy(entry)
            self.assertTrue(self.run_step(r)[0]);r.action.assert_not_called()
            self.assertEqual(r.s[recorded][d['key']],entry)

    def test_locked_or_unselected_named_entry_does_not_archive_old_or_advance(self):
        f,d,rows,_=self.fixture()
        old=dict(episode=5,chapter=10,stage=8,key='E5-C10-S8')
        for change in ('locked','unselected','later_chapter','later_stage'):
            target=copy.deepcopy(d)
            if change=='locked':target.update(locked=True,lock_score=.99)
            elif change=='unselected':target['cyan']=0
            elif change=='later_chapter':target['chapter']=2
            else:target['stage']=2
            fact=map_progress_fact(f,old,target,rows)
            self.assertFalse(fact.completed);self.assertFalse(fact.forward_unlocked)

    def test_numbered_episode_transition_requires_next_episode_first_chapter_first_node(self):
        source=dict(episode=5,chapter=10,stage=8)
        self.assertTrue(episode_handoff(source,dict(episode=6,chapter=1,stage=1)))
        for ep,ch,st in ((4,1,1),(7,1,1),(6,2,1),(6,1,2)):
            self.assertFalse(episode_handoff(source,dict(episode=ep,chapter=ch,stage=st)))

    def test_corrupt_identity_or_unknown_lock_does_not_authorize_handoff(self):
        f,d,rows,entry=self.fixture()
        for patch_value in ({'episode':'unknown'},{'locked':None},{'lock_score':None}):
            target=dict(d,**patch_value)
            fact=map_progress_fact(f,dict(entry,episode=5),target,rows)
            self.assertFalse(fact.completed);self.assertFalse(fact.forward_unlocked)

    def test_archive_write_failure_prevents_new_named_entry(self):
        f,d,_,_=self.fixture();r=fake_runner(f)
        old=dict(episode=5,chapter=10,stage=8,key='E5-C10-S8',entry_kind='story_only',cost=0)
        r.s.update(active=old,attempted={old['key']:copy.deepcopy(old)})
        r.save=Mock(side_effect=OSError('disk full'))
        with self.assertRaises(OSError):self.run_step(r)
        r.action.assert_not_called()
        self.assertNotIn(d['key'],r.s['attempted'])


class NativeStoryTeamTests(unittest.TestCase):
    @staticmethod
    def team():
        f=frame([('准备战斗',148,42),('故事队伍',86,120),('故事队伍',292,113),
            ('故事',501,218),('故事',700,276),('闯关成功',1260,232),
            ('配置1名黑暗属性英雄到队伍中',1372,268),
            ('配置1名魔导士职业英雄到队伍中',1385,302),
            ('登场的敌人',1264,361),('队伍战斗力',390,797),('管理队伍',90,850),
            ('托管战斗',820,718),('进行任务',1432,820),('精灵王的契约者',1240,160),('8/278',1264,820)])
        for y in (228,264,298):
            runner.cv2.fillConvexPoly(f.image,runner.np.array([(1188,y-16),(1199,y),(1188,y+16),(1177,y)],runner.np.int32),(50,180,230))
        return f

    def test_current_fixed_story_party_uses_only_ordinary_single_task_button(self):
        from story_core import team_entry_control
        f=self.team();control=team_entry_control(f)
        self.assertEqual(control['kind'],'single_task')
        self.assertEqual(control['target']['text'],'进行任务')
        self.assertIn('未操作托管',control['proof'])

    def test_objective_types_are_generic_not_a_current_title_or_role_exception(self):
        from story_core import team_entry_control
        for attribute in ('火焰','寒气','自然','光明','黑暗'):
            for role in ('骑士','战士','盗贼','魔导士','精灵师','射手'):
                f=self.team();f.words[6]['text']=f'配置1名{attribute}属性英雄到队伍中'
                f.words[7]['text']=f'配置1名{role}职业英雄到队伍中'
                self.assertEqual(team_entry_control(f)['kind'],'single_task')

    def test_each_anchor_is_required_unique_confident_and_in_its_current_region(self):
        from story_core import team_entry_control
        for index in (0,1,2,5,6,7,8,9,10,11,12):
            for change in ('missing','weak','duplicate','shifted'):
                with self.subTest(index=index,change=change):
                    f=self.team()
                    if change=='missing':f.words.pop(index)
                    elif change=='weak':f.words[index]['score']=.949
                    elif change=='duplicate':f.words.append(copy.deepcopy(f.words[index]))
                    else:f.words[index]['y']=500
                    self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_fixed_story_tags_are_required(self):
        from story_core import team_entry_control
        f=self.team();f.words=[w for w in f.words if w['text']!='故事']
        self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_hosted_dialog_repeat_auto_or_confirmation_never_falls_through(self):
        from story_core import team_entry_control
        for text,x,y in (('托管战斗',1460,115),('重复战斗',800,440),('托管中',800,440),
                         ('确认',935,575),('取消',650,575),('辅助英雄',1000,575)):
            f=self.team();f.words+=frame([(text,x,y)]).words
            self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_native_story_auto_off_or_on_does_not_delay_single_entry(self):
        from story_core import team_entry_control
        from test_team_preparation import prepared_runner,step
        for enabled in (False,True):
            f=self.team();f.words+=frame([('AUTO',1024,680)]).words
            if enabled:f.image[665:700,900:1095]=(0,200,0)
            self.assertEqual(team_entry_control(f)['kind'],'single_task')
            r=prepared_runner(f);r.ticket['name']='精灵王的契约者'
            step(r);self.assertEqual(r.action.call_args.args[0],'进行任务（仅一次入场）')
            self.assertEqual(r.action.call_args.args[1]['text'],'进行任务')
            self.assertEqual(r.s['active']['team_entry_mode'],'single_task')
            self.assertEqual(len(r.s['entry_dispatches'][r.s['active']['key']]),1)
            r.action.reset_mock();step(r);r.action.assert_not_called()

    def test_passive_mission_wording_does_not_gate_same_verified_single_entry_layout(self):
        from story_core import team_entry_control
        for objectives in [('3名以上英雄存活','未使用攻略英雄、继续战斗'),
                           ('2名以上英雄存活','未使用魂力燃烧技能'),
                           ('完成故事','1名以上英雄存活')]:
            f=self.team();f.words[6]['text'],f.words[7]['text']=objectives
            f.words+=frame([('AUTO',1024,680)]).words
            self.assertEqual(team_entry_control(f)['kind'],'single_task')

    def test_complete_task_diamond_panel_required_not_just_unknown_text(self):
        from story_core import team_entry_control
        for change in ('absent','one_missing','green','dim','rectangle'):
            f=self.team();f.words[6]['text']='3名以上英雄存活';f.words[7]['text']='未使用攻略英雄、继续战斗'
            f.words+=frame([('AUTO',1024,680)]).words
            if change=='absent':f.image[210:330,1160:1210]=22
            elif change=='one_missing':f.image[287:322,1160:1210]=22
            elif change=='green':f.image[210:330,1160:1210]=(0,220,0)
            elif change=='dim':f.image[210:330,1160:1210]//=4
            else:f.image[210:330,1160:1210]=(50,180,230)
            self.assertEqual(team_entry_control(f)['kind'],'unknown',change)

    def test_native_optional_multiple_glowing_slots_are_not_forced_hero_configuration(self):
        from story_core import team_entry_control
        for change in ('normal','single','no_auto','guide','partial'):
            f=self.team();f.words+=frame([('AUTO',1024,680)]).words
            slots=[(375,562)] if change=='single' else [(375,562),(562,652)]
            for x,y in slots:
                runner.cv2.ellipse(f.image,(x,y),(125,60),0,0,360,(0,230,255),12)
                runner.cv2.ellipse(f.image,(x,y),(135,69),0,0,360,(235,170,10),3)
            if change=='no_auto':f.words=[w for w in f.words if w['text']!='AUTO']
            elif change=='guide':f.words+=frame([('请配置当前教学英雄',800,450)]).words
            elif change=='partial':f.words=[w for w in f.words if w['text']!='登场的敌人']
            self.assertEqual(team_entry_control(f)['kind'],'single_task' if change in ('normal','no_auto') else 'unknown',change)

    def test_mission_glyphs_follow_current_text_rows_with_small_layout_offset(self):
        from story_core import team_entry_control
        f=self.team();f.words+=frame([('AUTO',1024,680)]).words
        f.image[203:333,1168:1209]=f.image[200:330,1168:1209].copy()
        for w in f.words:
            if 200<w['y']<330:w['y']+=3
        self.assertEqual(team_entry_control(f)['kind'],'single_task')

    def test_decorative_power_arrow_gets_one_current_field_read_without_lowering_confidence(self):
        from tutorial_ocr import strengthen_preparation_power_label
        f=self.team();original=f.words[9];original.update(text='▲队伍战斗力',score=.878)
        before=copy.deepcopy(original);ocr=Mock(return_value=([['队伍战斗力',.999]],None));at=f.at
        strengthen_preparation_power_label(f,ocr)
        ocr.assert_called_once();self.assertEqual(ocr.call_args.kwargs,dict(use_det=False,use_cls=False))
        self.assertEqual(f.at,at);self.assertEqual(f.words[9],before)
        self.assertEqual(f.words[-1]['original_ocr'],before)
        self.assertEqual(f.words[-1]['verification_scores'],[.999])
        self.assertEqual(f.words[-1]['source'],'current_preparation_power_label_field_read')

    def test_generic_objective_entry_glitter_gets_one_current_field_not_chapter_rules(self):
        from tutorial_ocr import strengthen_preparation_entry_label
        from story_core import team_entry_control
        for label in ('←进行任务','进行任务+','进行任务'):
            f=self.team();f.words[12].update(text=label,score=.876)
            old=copy.deepcopy(f.words[12]);ocr=Mock(return_value=([['进行任务',.999]],None));at=f.at
            strengthen_preparation_entry_label(f,ocr);strengthen_preparation_entry_label(f,ocr)
            ocr.assert_called_once();self.assertEqual(f.at,at);self.assertEqual(f.words[12],old)
            self.assertEqual(f.words[-1]['original_ocr'],old)
            self.assertEqual(team_entry_control(f)['kind'],'single_task')
            f.words.insert(12,copy.deepcopy(old))
            self.assertEqual(team_entry_control(f)['kind'],'unknown')
        f=self.team();f.words[12].update(text='←进行任务',score=.876);f.image[:]=22
        ocr=Mock();strengthen_preparation_entry_label(f,ocr);ocr.assert_not_called()

    def test_supplement_must_bind_this_frame_and_unchanged_original(self):
        from tutorial_ocr import strengthen_preparation_entry_label,strengthen_preparation_power_label
        from story_core import team_entry_control
        for index,text,helper in ((9,'－队伍战斗力',strengthen_preparation_power_label),(12,'←进行任务',strengthen_preparation_entry_label)):
            for change in ('stale','changed_source','changed_score'):
                f=self.team();f.words[index].update(text=text,score=.882)
                helper(f,Mock(return_value=([['队伍战斗力' if index==9 else '进行任务',.999]],None)))
                self.assertEqual(team_entry_control(f)['kind'],'single_task')
                if change=='stale':f.at+=1
                elif change=='changed_source':f.words[index]['text']='其他正文'
                else:f.words[-1]['verification_scores']=[.97]
                self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_decorative_dash_and_weak_power_use_one_bound_field_not_duplicate_control(self):
        from tutorial_ocr import strengthen_preparation_power_label
        from story_core import team_entry_control
        for prefix in ('－','—','−',''):
            f=self.team();f.words[9].update(text=prefix+'队伍战斗力',score=.882)
            original=copy.deepcopy(f.words[9]);ocr=Mock(return_value=([['队伍战斗力',.999]],None))
            strengthen_preparation_power_label(f,ocr);strengthen_preparation_power_label(f,ocr)
            ocr.assert_called_once();self.assertEqual(f.words[9],original)
            self.assertEqual(team_entry_control(f)['kind'],'single_task')
            f.words.insert(9,copy.deepcopy(original))
            self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_power_field_weak_changed_or_ambiguous_read_never_strengthens(self):
        from tutorial_ocr import strengthen_preparation_power_label
        for rows in ([['队伍战斗力',.979]],[['其他文字',.999]],[['队伍战斗力',.999],['队伍战斗力',.999]],[]):
            f=self.team();f.words[9].update(text='▲队伍战斗力',score=.878);before=copy.deepcopy(f.words)
            ocr=Mock(return_value=(rows,None));strengthen_preparation_power_label(f,ocr)
            ocr.assert_called_once();self.assertEqual(f.words,before)

    def test_power_field_complete_label_partial_page_or_duplicate_source_is_not_read(self):
        from tutorial_ocr import strengthen_preparation_power_label
        for change in ('complete','partial','duplicate'):
            f=self.team()
            if change!='complete':f.words[9].update(text='▲队伍战斗力',score=.878)
            if change=='partial':f.words=[w for w in f.words if w['text']!='登场的敌人']
            elif change=='duplicate':f.words.append(copy.deepcopy(f.words[9]))
            ocr=Mock();strengthen_preparation_power_label(f,ocr);ocr.assert_not_called()

    def test_native_story_auto_variations_are_optional_but_partial_dialog_or_selector_still_veto(self):
        from story_core import team_entry_control
        for change in ('weak','duplicate','shifted','missing_anchor','dialog','support_selector'):
            f=self.team();f.words+=frame([('AUTO',1024,680)]).words
            if change=='weak':f.words[-1]['score']=.979
            elif change=='duplicate':f.words.append(copy.deepcopy(f.words[-1]))
            elif change=='shifted':f.words[-1]['y']=440
            elif change=='missing_anchor':f.words=[w for w in f.words if w['text']!='登场的敌人']
            elif change=='dialog':f.words+=frame([('确认',935,575)]).words
            else:f.words+=frame([('辅助英雄',1000,575)]).words
            self.assertEqual(team_entry_control(f)['kind'],'single_task' if change in ('weak','duplicate','shifted') else 'unknown',change)

    def test_story_task_does_not_configure_heroes_or_enable_hosted_battle(self):
        from test_team_preparation import prepared_runner,step
        f=self.team();r=prepared_runner(f)
        r.ticket.update(episode=named_episode('亚奇'),chapter=1,stage=2,name='精灵王的契约者')
        r.ticket['key']=stage_key(r.ticket)
        before=copy.deepcopy(r.s['attempted'])
        self.assertTrue(step(r)[0]);r.action.assert_called_once()
        self.assertEqual(r.action.call_args.args[0],'进行任务（仅一次入场）')
        a=r.s['active'];self.assertEqual(a['cost'],8)
        self.assertEqual(a['team_entry_mode'],'single_task')
        self.assertEqual(r.s['entry_dispatches'][a['key']][0]['status'],'sent')
        for key,value in before.items():self.assertEqual(r.s['attempted'][key],value)
        r.action.reset_mock();self.assertTrue(step(r)[0]);r.action.assert_not_called()
        self.assertEqual(len(r.s['entry_dispatches'][a['key']]),1)

    def test_map_name_resource_and_history_guards_remain_before_first_send(self):
        from test_team_preparation import prepared_runner,step
        for condition in ('missing_map','wrong_title','resource','attempted'):
            f=self.team();r=prepared_runner(f);r.ticket['name']='精灵王的契约者'
            key=r.ticket['key']
            if condition=='missing_map':r.ticket=None
            elif condition=='wrong_title':r.ticket['name']='other title'
            elif condition=='resource':f.words[-1]['text']='8/0'
            else:r.s['attempted'][key]=dict(outcome='unknown',keep='original')
            try:step(r)
            except runner.TaskAttention:pass
            r.action.assert_not_called()
            self.assertFalse(r.s.get('entry_dispatches'))


if __name__=='__main__':unittest.main()
