"""Preparation-layout regressions. All actions and persistence are fake."""
import copy
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import runner
from entry_journal import can_enter
from pc_backend import InputDeliveryError
from story_core import team_entry_control, read_stage
from task_blockers import TaskAttention
from test_map_layout import frame, fake_runner
from test_story import make as story_runner


ANCHORS = [('准备战斗',148,42), ('托管战斗',1460,115), ('托管战斗',822,727),
           ('一队伍战斗力',392,805), ('管理队伍',92,859), ('辅助英雄',1000,575), ('进行任务',1435,828)]


def preparation(extra=()):
    return frame([*ANCHORS, ('新关卡',1220,168), ('20/100',1267,831), *extra])


def prepared_runner(f):
    r=fake_runner(f)
    r.ticket=dict(key='E1-C1-S2',name='新关卡',phase='support',verified_epoch=time.time(),
                  episode=1,chapter=1,stage=2)
    r.s['attempted']['old-failure']={'outcome':'defeat','evidence':'preserve'}
    return r


def step(r):
    with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-team-test')):
        return r.step(r.frame)


class TeamPreparationTests(unittest.TestCase):
    def episode_party(self):
        return frame([('准备战斗',148,42),('Episode1队',87,121),('Episode2队',87,197),('Episode3队',87,271),
                      ('闯关成功',1262,233),('完成故事',1261,268),('1名以上英雄存活',1305,303),
                      ('登场的敌人',1267,361),('辅助英雄无法参与',1000,605),('·队伍战斗力',399,797),
                      ('管理队伍',92,851),('进行任务',1434,821),('新关卡',1220,168),('8/542',1267,831)])

    def test_native_episode_party_without_eligible_support_is_single_entry_only(self):
        f=self.episode_party();control=team_entry_control(f);self.assertEqual(control['kind'],'single_task')
        self.assertEqual(control['target']['text'],'进行任务');self.assertIn('不推断',control['proof'])
        r=prepared_runner(f);old=copy.deepcopy(r.s['attempted']);step(r)
        self.assertEqual(r.action.call_count,1);self.assertEqual(r.s['active']['cost'],8)
        self.assertEqual(r.s['entry_dispatches']['E1-C1-S2'][0]['status'],'sent')
        self.assertEqual(r.s['completed'],{});self.assertEqual(r.s['attempted']['old-failure'],old['old-failure'])

    def test_native_episode_party_missing_weak_duplicate_or_shifted_anchor_is_unknown(self):
        for i in (0,1,2,3,4,5,6,7,9,10,11):
            for mode in ('missing','weak','duplicate','shifted'):
                f=self.episode_party()
                if mode=='missing':f.words.pop(i)
                elif mode=='weak':f.words[i]['score']=.899 if i==9 else .979
                elif mode=='duplicate':f.words.append(copy.deepcopy(f.words[i]))
                else:f.words[i]['x']=1600
                self.assertEqual(team_entry_control(f)['kind'],'unknown',(i,mode))

    def test_native_episode_party_selector_and_hosted_or_dialog_never_enter(self):
        for text in ('托管战斗','重复战斗','确认','取消','搜索'):
            f=self.episode_party();f.words+=frame([(text,1500 if text=='搜索' else 800,115 if text=='搜索' else 500)]).words
            if text=='搜索':f.words+=frame([('等级',1318,113),('维多丽卡',1347,324)]).words
            self.assertEqual(team_entry_control(f)['kind'],'unknown',text)

    def test_story_fixed_team_without_auto_is_only_normal_single_entry(self):
        words=[('准备战斗',148,42),('故事队伍',84,120),('故事队伍',291,112),('故事',699,217),
               ('闯关成功',1259,233),('完成故事',1258,268),('1名以上英雄存活',1300,301),
               ('登场的敌人',1264,360),('队伍战斗力',391,797),('管理队伍',89,851),('进行任务',1432,818)]
        f=frame([*words,('新关卡',1239,161),('8/82',1264,824)])
        self.assertEqual(team_entry_control(f)['kind'],'single_task')
        r=prepared_runner(f);step(r);self.assertEqual(r.s['active']['cost'],8)
        for index in range(len(words)):
            altered=frame([*words,('新关卡',1239,161),('8/82',1264,824)])
            altered.words[index]['score']=.89 if index==8 else .90
            self.assertEqual(team_entry_control(altered)['kind'],'unknown')
        f=frame([*words,('新关卡',1239,161),('8/82',1264,824),('托管战斗',1400,120)])
        self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_empty_support_layout_uses_only_observed_single_task_button(self):
        f=preparation();control=team_entry_control(f)
        self.assertEqual(control['kind'],'single_task')
        self.assertIs(control['target'],f.find(r'^进行任务$'))
        r=prepared_runner(f);step(r)
        self.assertEqual(r.action.call_count,1)
        self.assertEqual(r.action.call_args.args[1]['text'],'进行任务')
        self.assertEqual(r.s['active']['team_entry_mode'],'single_task')
        self.assertIn('未操作托管',r.s['active']['team_entry_proof'])
        self.assertEqual(r.s['completed'],{})

    def test_entry_is_persisted_before_dispatch_and_old_failure_is_untouched(self):
        r=prepared_runner(preparation());saved=[]
        r.save.side_effect=lambda:saved.append(copy.deepcopy(r.s))
        def dispatch(*args):
            self.assertEqual(saved[-1]['entry_dispatches']['E1-C1-S2'][-1]['status'],'reserved')
            self.assertIn('E1-C1-S2',saved[-1]['attempted'])
        r.action.side_effect=dispatch;step(r)
        self.assertEqual(r.s['entry_dispatches']['E1-C1-S2'][-1]['status'],'sent')
        self.assertEqual(r.s['attempted']['old-failure'],{'outcome':'defeat','evidence':'preserve'})

    def test_missing_low_confidence_or_displaced_anchor_does_not_allow_entry(self):
        for index in (0,1,2,3,4,6):  # Optional support occupancy is not an entry gate.
            for change in ('missing','low_score','moved'):
                with self.subTest(index=index,change=change):
                    f=preparation()
                    if change=='missing':f.words.pop(index)
                    elif change=='low_score':f.words[index]['score']=.89
                    else:f.words[index]['x']=600;f.words[index]['y']=400
                    f.image[650:710,900:1095]=(0,200,0)
                    r=prepared_runner(f);step(r)
                    self.assertEqual(team_entry_control(f)['kind'],'unknown')
                    r.action.assert_not_called();self.assertNotIn('E1-C1-S2',r.s['attempted'])

    def test_partial_hosted_page_cannot_be_authorized_by_auto(self):
        for auto in (False,True):
            with self.subTest(auto=auto):
                f=preparation([('AUTO',990,680)] if auto else [])
                f.words.pop(0);f.image[650:710,900:1095]=(0,200,0)
                r=prepared_runner(f);step(r);r.action.assert_not_called()
                self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_repeat_setup_or_ambiguous_task_label_is_not_single_entry(self):
        for extra in ('重复战斗','连续战斗','托管次数','托管中'):
            r=prepared_runner(preparation([(extra,800,400)]));step(r)
            r.action.assert_not_called();self.assertNotIn('E1-C1-S2',r.s['attempted'])
        f=preparation();f.find('^进行任务$')['text']='重复进行任务'
        self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_current_team_without_map_proof_returns_once_without_entering(self):
        r=prepared_runner(preparation());r.ticket=None;step(r)
        r.back.assert_called_once();r.action.assert_not_called()
        self.assertNotIn('E1-C1-S2',r.s['attempted'])

    def test_stale_map_proof_or_wrong_stage_name_still_blocks_entry(self):
        for invalid in ('expired','wrong_title'):
            r=prepared_runner(preparation())
            if invalid=='expired':r.ticket['verified_epoch']=time.time()-121
            else:r.ticket['name']='另一个目标'
            step(r);r.action.assert_not_called();self.assertNotIn('E1-C1-S2',r.s['attempted'])

    def test_low_stamina_or_unclear_cost_never_reserves_entry(self):
        for invalid in ('insufficient','unclear'):
            r=prepared_runner(preparation());word=r.frame.find('20/100')
            if invalid=='insufficient':word['text']='20/5'
            else:word['score']=.89
            try:step(r)
            except TaskAttention:pass
            r.action.assert_not_called();self.assertNotIn('E1-C1-S2',r.s['attempted'])

    def test_previous_attempt_completed_or_active_is_never_repeated(self):
        for bucket in ('attempted','completed','active'):
            r=prepared_runner(preparation())
            if bucket=='active':r.s[bucket]={'key':'E1-C1-S2'}
            else:r.s[bucket]['E1-C1-S2']={'outcome':'preserve'}
            try:step(r)
            except TaskAttention:pass
            r.action.assert_not_called()

    def test_persistence_error_is_zero_input(self):
        r=prepared_runner(preparation());r.save.side_effect=OSError('disk full')
        with self.assertRaises(OSError):step(r)
        r.action.assert_not_called()

    def test_uncertain_dispatch_does_not_allow_another_entry(self):
        r=prepared_runner(preparation());r.action.side_effect=InputDeliveryError('delivery unknown')
        with self.assertRaises(InputDeliveryError):step(r)
        self.assertFalse(can_enter(r.s,'E1-C1-S2'))
        original=copy.deepcopy(r.s['active'])
        r.action.reset_mock();r.action.side_effect=None
        self.assertTrue(step(r)[0])
        r.action.assert_not_called();r.back.assert_not_called()
        self.assertTrue(all(r.s['active'].get(k)==v for k,v in original.items()))
        self.assertNotIn('unresolved_entries',r.s)

    def test_resource_capacity_and_confirmation_overlays_keep_priority(self):
        for text,scene in [('是否使用生命之叶补充体力','resource_stop'),
                           ('装备背包已满','capacity_stop'),('确认','unknown_dialog')]:
            f=preparation([(text,800,400)]);self.assertEqual(runner.classify(f),scene)
            r=prepared_runner(f)
            with self.assertRaises(TaskAttention):step(r)
            r.action.assert_not_called();self.assertNotIn('E1-C1-S2',r.s['attempted'])

    def test_legacy_auto_state_does_not_delay_or_replace_the_single_entry(self):
        for enabled in (False,True):
            f=preparation([('AUTO',990,680)])
            f.words=[w for w in f.words if w['text']!='辅助英雄']
            if enabled:f.image[650:710,900:1095]=(0,200,0)
            r=prepared_runner(f);step(r)
            self.assertEqual(r.action.call_count,1)
            self.assertEqual(r.action.call_args.args[1]['text'],'进行任务')
            self.assertEqual(r.s['active']['team_entry_mode'],'single_task')
            self.assertEqual(len(r.s['entry_dispatches']['E1-C1-S2']),1)
            r.action.reset_mock();step(r);r.action.assert_not_called()

    def test_green_portrait_cannot_authorize_incomplete_preparation_layout(self):
        f=frame([('进行任务',1435,828),('队伍战斗力',392,805),('新关卡',1220,168),('20/100',1267,831)])
        f.image[650:710,900:1095]=(0,200,0)
        self.assertEqual(team_entry_control(f)['kind'],'unknown');r=prepared_runner(f);step(r);r.action.assert_not_called()

    def test_story_uses_same_single_entry_layout_without_enabling_hosted_mode(self):
        f=preparation([('目标地区',1220,115)])
        f.words[len(ANCHORS)]['text']='1-4.目标剧情'
        r,story=story_runner(f);story.goal=False;stage=read_stage(f);story.bind(stage['region'])
        story.enter(f,stage,f.find('进行任务'))
        self.assertEqual(r.action.call_count,1)
        self.assertEqual(r.action.call_args.kwargs['word']['text'],'进行任务')
        self.assertEqual(story.book['active']['team_entry_mode'],'single_task')
        self.assertIn('未操作托管',story.book['active']['proof'])
        self.assertEqual(story.book['completed'],{})

    def test_saved_reported_screen_plans_only_single_entry_without_live_input(self):
        folder=Path(os.environ.get('EPIC7_TEAM_FIXTURES',str(Path(__file__).resolve().parents[1]/'.local/team-preparation-2026-11-04')))
        image_path=folder/'team.png';ocr_path=folder/'team-ocr.json'
        if not image_path.is_file() or not ocr_path.is_file():
            self.skipTest('Private team screenshot/OCR not distributed')
        data=json.loads(ocr_path.read_text(encoding='utf-8'))
        image=runner.cv2.imdecode(runner.np.frombuffer(image_path.read_bytes(),runner.np.uint8),runner.cv2.IMREAD_COLOR)
        f=runner.Frame(image,[(w['box'],w['text'],w['score']) for w in data['words']])
        self.assertEqual(runner.classify(f),'team');self.assertIsNone(f.find('^AUTO$'))
        r=prepared_runner(f);r.ticket['name']=f.find('.+',(1140,145,1560,195))['text']
        step(r)
        self.assertEqual(r.action.call_count,1)
        self.assertIs(r.action.call_args.args[1],f.find('^进行任务$'))
        self.assertEqual(r.s['active']['team_entry_mode'],'single_task')
