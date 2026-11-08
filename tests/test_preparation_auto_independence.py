"""Preparation entry is independent of AUTO; no live devices, input or profiles."""
import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import runner
import test_team_preparation as preparations
import test_named_episode as named
from test_map_layout import frame
from test_story import make as story_runner
from entry_preparation import _target, EntryPreparationDeferred
from story_core import team_entry_control, read_stage
from task_blockers import TaskAttention


AUTO_VARIANTS=('missing','off','on','reported_position','weak','duplicate','elsewhere')


def episode():
    f=preparations.TeamPreparationTests().episode_party()
    f.words=[w for w in f.words if w['text']!='辅助英雄无法参与']
    f.words[6]['text']='2名以上英雄存活'
    return f


def legacy_story(button='进行任务'):
    return frame([('准备战斗',148,42),('支线故事1队',89,128),
        ('没有可执行的',1378,279),('任务。',1378,301),('登场的敌人',1269,367),
        ('可获得的奖励',1264,581),('队伍战斗力',396,804),('管理队伍',95,857),
        ('托管战斗',825,725),(button,1438,825),('1-4.目标剧情',1245,166),
        ('目标地区',1242,116),('8/100',1271,829)])


def vary_auto(f,variant):
    f.words=[w for w in f.words if w['text']!='AUTO']
    if variant!='missing':
        x,y=(1021.5,619.5) if variant=='reported_position' else (990,680)
        if variant=='elsewhere':x,y=400,400
        f.words+=frame([('AUTO',x,y)]).words
        if variant=='weak':f.words[-1]['score']=.60
        elif variant=='duplicate':f.words.append(copy.deepcopy(f.words[-1]))
        elif variant=='on':f.image[650:710,900:1095]=(0,200,0)
    f.text='\n'.join(w['text'] for w in f.words);f.clean=runner.norm(f.text)
    return f


class AutoIndependentPreparationTests(unittest.TestCase):
    def layouts(self):
        return (preparations.preparation,episode,named.NativeStoryTeamTests.team,
                legacy_story,lambda:legacy_story('战斗开始'))

    def test_all_known_layouts_ignore_auto_presence_position_state_and_confidence(self):
        for make in self.layouts():
            for variant in AUTO_VARIANTS:
                with self.subTest(layout=make,auto=variant):
                    f=vary_auto(make(),variant);before=copy.deepcopy(f.words)
                    control=team_entry_control(f)
                    self.assertEqual(control['kind'],'single_task')
                    self.assertIn(control['target']['text'],('进行任务','战斗开始'))
                    self.assertEqual(f.words,before)

    def test_reader_never_requests_auto_detection_or_state_to_authorize_entry(self):
        for make in self.layouts():
            f=make();original=f.find
            def read(pattern,*args,**kwargs):
                self.assertNotIn('AUTO',pattern)
                return original(pattern,*args,**kwargs)
            with patch.object(f,'find',side_effect=read):
                self.assertEqual(team_entry_control(f)['kind'],'single_task')

    def test_support_occupancy_is_not_an_alternative_hard_requirement(self):
        for make in (preparations.preparation,episode):
            for support in ('missing','辅助英雄','辅助英雄无法参与','已选择的辅助英雄'):
                f=make();f.words=[w for w in f.words if '辅助英雄' not in w['text']]
                if support!='missing':f.words+=frame([(support,1000,575)]).words
                for variant in ('missing','reported_position'):
                    self.assertEqual(team_entry_control(vary_auto(f,variant))['kind'],'single_task')

    def test_reported_episode_layout_enters_once_without_tapping_auto(self):
        f=vary_auto(episode(),'reported_position');r=preparations.prepared_runner(f)
        old=copy.deepcopy(r.s['attempted']);preparations.step(r)
        self.assertEqual(r.action.call_count,1)
        self.assertEqual(r.action.call_args.args[1]['text'],'进行任务')
        self.assertEqual(r.s['active']['team_entry_mode'],'single_task')
        self.assertEqual(len(r.s['entry_dispatches']['E1-C1-S2']),1)
        self.assertEqual(r.s['attempted']['old-failure'],old['old-failure'])
        self.assertEqual(r.s['completed'],{})
        r.action.reset_mock();preparations.step(r);r.action.assert_not_called()

    def test_auto_or_green_pixels_cannot_authorize_an_incomplete_unknown_layout(self):
        for variant in AUTO_VARIANTS:
            f=vary_auto(frame([('进行任务',1435,828),('队伍战斗力',392,805),
                               ('新关卡',1220,168),('20/100',1267,831)]),variant)
            f.image[650:710,900:1095]=(0,200,0)
            self.assertEqual(team_entry_control(f)['kind'],'unknown')
            r=preparations.prepared_runner(f);preparations.step(r);r.action.assert_not_called()

    def test_entry_must_still_be_unique_confident_and_in_the_verified_region(self):
        for make in self.layouts():
            for change in ('missing','weak','moved','duplicate','mixed_entry'):
                f=vary_auto(make(),'missing')
                w=next(w for w in f.words if w['text'] in ('进行任务','战斗开始'))
                if change=='missing':f.words.remove(w)
                elif change=='weak':w['score']=.89
                elif change=='moved':w['x']=800
                elif change=='duplicate':f.words.append(copy.deepcopy(w))
                else:f.words+=frame([('战斗开始' if w['text']=='进行任务' else '进行任务',1438,825)]).words
                self.assertEqual(team_entry_control(f)['kind'],'unknown',(make,change))

    def test_original_resource_capacity_defeat_and_unknown_dialog_veto_still_win(self):
        for text in ('是否使用生命之叶补充体力','装备背包已满','战斗失败','确认'):
            r=preparations.prepared_runner(vary_auto(preparations.preparation([(text,800,400)]),'missing'))
            try:preparations.step(r)
            except TaskAttention:pass
            r.action.assert_not_called();self.assertNotIn('E1-C1-S2',r.s['attempted'])

    def test_removing_auto_never_bypasses_persistence_or_original_entry_history(self):
        for variant in AUTO_VARIANTS:
            r=preparations.prepared_runner(vary_auto(preparations.preparation(),variant))
            r.save.side_effect=OSError('disk full')
            with self.assertRaises(OSError):preparations.step(r)
            r.action.assert_not_called()
            r=preparations.prepared_runner(vary_auto(preparations.preparation(),variant))
            r.s['attempted']['E1-C1-S2']={'outcome':'unknown','evidence':'preserve'}
            before=copy.deepcopy(r.s['attempted']);preparations.step(r)
            r.action.assert_not_called();self.assertEqual(r.s['attempted'],before)

    def test_uninvoked_legacy_auto_on_reservation_revalidates_without_rewriting_history(self):
        for mode in ('single_task','auto_on'):
            for variant in AUTO_VARIANTS:
                r=preparations.prepared_runner(vary_auto(preparations.preparation(),variant))
                r.s['active']=dict(key='E1-C1-S2',cost=20,team_entry_mode=mode)
                before=copy.deepcopy(r.s)
                target=_target(r,dict(action='进行任务（仅一次入场）'))
                self.assertEqual(target['text'],'进行任务');self.assertEqual(r.s,before)
                r.action.assert_not_called()

    def test_unknown_old_mode_changed_cost_or_insufficient_stock_never_dispatches(self):
        for change in ('unknown_mode','changed_cost','insufficient'):
            r=preparations.prepared_runner(preparations.preparation())
            r.s['active']=dict(key='E1-C1-S2',cost=20,team_entry_mode='auto_on')
            if change=='unknown_mode':r.s['active']['team_entry_mode']='enable_auto'
            else:r.frame.find('20/100')['text']='21/100' if change=='changed_cost' else '20/19'
            with self.assertRaises(EntryPreparationDeferred):_target(r,dict(action='进行任务（仅一次入场）'))
            r.action.assert_not_called()

    def test_legacy_story_and_defense_enter_directly_without_preparation_auto(self):
        for button in ('进行任务','战斗开始'):
            for variant in AUTO_VARIANTS:
                f=vary_auto(legacy_story(button),variant);r,story=story_runner(f)
                story.goal=False;stage=read_stage(f);story.bind(stage['region'])
                original=copy.deepcopy(r.s['attempted'])
                story.enter(f,stage,f.find(button))
                self.assertEqual(r.action.call_count,1)
                self.assertEqual(r.action.call_args.kwargs['word']['text'],button)
                self.assertEqual(story.book['active']['team_entry_mode'],'single_task')
                self.assertEqual(story.book['completed'],{});self.assertEqual(r.s['attempted'],original)

    def test_legacy_story_layout_keeps_each_required_field_and_hosted_overlay_guard(self):
        for index in range(8):
            f=legacy_story();f.words.pop(index)
            self.assertEqual(team_entry_control(f)['kind'],'unknown',index)
        for text,x,y in (('托管战斗',1460,115),('重复战斗',800,400),('确认',935,575)):
            f=legacy_story();f.words+=frame([(text,x,y)]).words
            self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_private_reported_screenshot_reader_replay_never_sends_input(self):
        folder=Path(os.environ.get('EPIC7_PREPARATION_AUTO_FIXTURES',str(Path(__file__).resolve().parents[1]/'.local/reported-team-stall-20261108')))
        image=folder/'attachment-client-normalized.png';ocr=folder/'attachment-ocr.json'
        if not image.is_file() or not ocr.is_file():self.skipTest('Private reported screenshot/OCR not distributed')
        data=json.loads(ocr.read_text(encoding='utf-8'))
        im=runner.cv2.imdecode(runner.np.frombuffer(image.read_bytes(),runner.np.uint8),runner.cv2.IMREAD_COLOR)
        f=runner.Frame(im,[(w['box'],w['text'],w['score']) for w in data['words']])
        control=team_entry_control(f)
        self.assertEqual(control['kind'],'single_task');self.assertEqual(control['target']['text'],'进行任务')


if __name__=='__main__':unittest.main()
