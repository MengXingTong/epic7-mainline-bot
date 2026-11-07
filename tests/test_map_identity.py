"""Branch-qualified map identity and automatic read-only evidence recovery."""
import copy
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import runner
from map_identity import parse_chapter,chapter_header,chapter_identity,same_chapter,stage_key,stage_order,native_forward_chapter
from mainline_map import clipped_story_completion
from test_map_layout import map_frame,fake_runner
from test_era_map import era_map


class MapIdentityTests(unittest.TestCase):
    def test_main_chapter_keys_are_byte_compatible_but_branches_never_alias(self):
        main=dict(episode=5,chapter=8,stage=1)
        branch=dict(main,chapter_suffix='S')
        self.assertEqual(stage_key(main),'E5-C8-S1')
        self.assertEqual(stage_key(branch),'E5-C8S-S1')
        self.assertFalse(same_chapter(main,branch))
        self.assertLess(stage_order(main),stage_order(branch))
        self.assertLess(stage_order(branch),stage_order(dict(episode=5,chapter=9,stage=1)))
    def test_numeric_and_letter_identities_ignore_story_titles_not_numbering(self):
        for text,expected in [('第8章 标题',dict(chapter=8)),('第8S章计划收尾',dict(chapter=8,chapter_suffix='S')),
                              ('第 ８ ｓ 章 未知的标题',dict(chapter=8,chapter_suffix='S')),
                              ('第12AB章',dict(chapter=12,chapter_suffix='AB'))]:
            self.assertEqual(parse_chapter(text),expected)
        for text in ('剧情第8章','第0章','第8?章','第S章','Episode 5','第八章'):
            self.assertIsNone(parse_chapter(text))
    def test_ambiguous_low_confidence_or_moved_header_does_not_authorize_a_map(self):
        for mode in ('duplicate','score','position'):
            f=map_frame()
            if mode=='duplicate':f.words.append(copy.deepcopy(f.words[1]))
            elif mode=='score':f.words[1]['score']=.84
            else:f.words[1]['y']=220
            self.assertEqual(chapter_header(f),(None,None))
            self.assertIsNone(runner.Runner.__new__(runner.Runner).map_ticket(f)[0])
    def test_same_stage_number_in_branch_is_a_distinct_new_entry(self):
        f=map_frame();f.words[0]['text']='Episode 5';f.words[1]['text']='第8S章计划收尾'
        r=fake_runner(f);r.s['attempted']['E5-C8-S5']={'old':True}
        r.s['completed']['E5-C8-S5']={'old':True}
        before=copy.deepcopy(r.s['attempted'])
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-map-identity-test')):
            keep,_=r.step(f)
        self.assertTrue(keep)
        self.assertEqual(r.ticket['key'],'E5-C8S-S5')
        self.assertEqual(r.s['attempted'],before)
        self.assertEqual(r.action.call_args.args[0],'未通关验证通过，准备战斗')
    def test_incomplete_identity_keeps_observing_without_expiring_into_attention(self):
        f=map_frame();f.words[1]['text']='未识别的章节字段';r=fake_runner(f);r.run_id='same-run'
        r.last_mode='map';r.mode_since=time.time()-600
        original=copy.deepcopy(r.s)
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-map-identity-test')):
            for _ in range(4):
                keep,_=r.step(f)
                self.assertTrue(keep)
                self.assertEqual(r.observation_wait['code'],'map_identity')
                r.action.assert_not_called()
            self.assertEqual(r.s['evidence_observations']['map_identity']['observations'],4)
            self.assertEqual(len(r.s['evidence_observations']['map_identity']['diagnostics']),1)
            f.words[1]['text']='第6章正确的选择';keep,_=r.step(f)
        self.assertTrue(keep)
        self.assertIsNone(r.observation_wait)
        self.assertEqual(r.action.call_count,1)
        self.assertEqual(r.s['attempted'],original['attempted'])
        self.assertEqual(r.s['completed'],original['completed'])
    def test_split_current_map_title_is_assembled_without_merging_other_rows(self):
        from mainline_map import complete_map_row_labels
        f=map_frame();anchor=f.words[2]
        anchor.update(text='5. 梦想、',x=172.,box=[[120,275],[224,275],[224,306],[120,306]])
        suffix=dict(text='迷恋与真实1',score=.99,x=309.,y=291.,box=[[230,276],[388,276],[388,306],[230,306]])
        f.words.append(suffix);before=copy.deepcopy(f.words)
        d,_,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
        self.assertEqual(d['name'],'梦想、迷恋与真实1');self.assertEqual(len(d['name_components']),2)
        self.assertEqual(f.words,before)
        for mode in ('low','row','gap','overlap'):
            test=copy.deepcopy(f)
            if mode=='low':test.words[-1]['score']=.84
            elif mode=='row':test.words[-1]['y']+=125
            elif mode=='gap':test.words[-1]['box']=[[300,276],[458,276],[458,306],[300,306]]
            else:test.words.append(copy.deepcopy(test.words[-1]))
            labels=complete_map_row_labels(test.words)
            self.assertEqual(labels[0]['text'],'5. 梦想、')

    def test_stale_mumu_map_navigation_is_replanned_without_input_or_manual_resume(self):
        from pc_backend import FrameExpired,NavigationFrameExpired,TapNotSent,NavigationInputDeferred
        f=map_frame();r=fake_runner(f);r.pc=None;r.s['screen']='map'
        r.action=runner.Runner.action.__get__(r,runner.Runner)
        r._action=lambda *args:(_ for _ in ()).throw(FrameExpired('before send'))
        with self.assertRaises(NavigationFrameExpired):r.action('未通关验证通过，准备战斗',{'x':1300,'y':830})
        r._action=lambda *args:(_ for _ in ()).throw(TapNotSent('not an ADB proof'))
        with self.assertRaises(TapNotSent) as caught:r.action('未通关验证通过，准备战斗',{'x':1300,'y':830})
        self.assertNotIsInstance(caught.exception,NavigationInputDeferred)
    def test_every_adapter_rejects_stale_planning_before_any_intent_is_created(self):
        from assistant_worker import PlanningFrameGate
        f=map_frame();f.at=time.time()-6;gate=PlanningFrameGate()
        self.assertFalse(gate.ready(None,f))
        f.at=time.time()+10;self.assertFalse(gate.ready(None,f))
        f.at=time.time();self.assertTrue(gate.ready(None,f))

    def test_wrong_branch_cannot_supply_a_clipped_predecessor_clear(self):
        f=era_map();d,rows,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
        entry=dict(episode=6,chapter=1,chapter_suffix='S',stage=1,name='original',entry_kind='story_only')
        self.assertIsNone(clipped_story_completion(f,entry,d,rows))
    def test_only_native_adjacent_main_branch_transitions_are_candidates(self):
        main=dict(episode=5,chapter=8)
        side=dict(main,chapter_suffix='S')
        nxt=dict(episode=5,chapter=9)
        self.assertTrue(native_forward_chapter(main,side))
        self.assertTrue(native_forward_chapter(side,nxt))
        for target in (main,dict(side,chapter_suffix='T'),dict(episode=5,chapter=10),dict(episode=6,chapter=9)):
            self.assertFalse(native_forward_chapter(side,target))


if __name__=='__main__':unittest.main()
