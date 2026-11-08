"""Variable-length chapters: current positive clear + native navigation only."""
import copy,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import runner
from mainline_map import chapter_navigation_control
from test_map_layout import frame,fake_runner

class VariableChapterTests(unittest.TestCase):
    def fixture(self,stage=6):
        f=frame([('外传Episode：亚奇',200,44),('第1章精灵王的契约者',190,137),
                 (f'{stage}.未知的遭遇',220,290),('观看故事',1400,827)])
        runner.cv2.polylines(f.image,[runner.np.array([(310,124),(321,136),(310,148)],runner.np.int32)],False,(220,220,220),5)
        d=dict(episode='named:亚奇',chapter=1,stage=stage,key=f'named-C1-S{stage}',
               locked=False,lock_score=.1,clear_badge=True,star_count=None,completion='cleared')
        return f,d,[d]
    def step(self,r):
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-variable-chapter-test')):return r.step(r.frame)
    def test_six_or_any_positive_final_stage_uses_current_chevron_not_fixed_stage_ten(self):
        for stage in (1,3,6,9,10,12):
            f,d,rows=self.fixture(stage);target=chapter_navigation_control(f,d,rows)
            self.assertIsNotNone(target,stage);self.assertEqual(target['source'],'native_chapter_heading_and_chevron')
            r=fake_runner(f);r.map_ticket=Mock(return_value=(d,rows,'已通关绿色勾'))
            self.assertTrue(self.step(r)[0]);r.action.assert_called_once_with('完成本章后进入下一章',target)
            self.assertEqual(r.s['completed'],{});self.assertFalse(r.s.get('entry_dispatches'))
    def test_uncompleted_missing_or_conflicting_lock_never_navigates(self):
        for change in ('uncompleted','locked','missing_header','weak_header','wrong_chapter','branch'):
            f,d,rows=self.fixture()
            if change=='uncompleted':d.update(completion='unconfirmed',clear_badge=False)
            elif change=='locked':d['locked']=True
            elif change=='missing_header':f.words.pop(1)
            elif change=='weak_header':f.words[1]['score']=.979
            elif change=='wrong_chapter':d['chapter']=2
            else:d['chapter_suffix']='S'
            self.assertIsNone(chapter_navigation_control(f,d,rows),change)
    def test_chapter_stars_or_reward_checks_are_not_current_node_clear(self):
        f,d,rows=self.fixture();d.update(completion='unconfirmed',clear_badge=False)
        f.words+=frame([('9/9',68,775),('已领取',190,845)]).words
        self.assertIsNone(chapter_navigation_control(f,d,rows))
    def test_visible_successor_or_unknown_chevron_never_implies_chapter_end(self):
        for change in ('next_locked','next_clear','absent','rectangle','left_arrow','duplicate'):
            f,d,rows=self.fixture()
            if change.startswith('next_'):rows.append(dict(d,stage=7,locked=change=='next_locked'))
            else:
                f.image[115:158,300:337]=22
                if change=='rectangle':f.image[125:145,310:324]=220
                elif change=='left_arrow':runner.cv2.polylines(f.image,[runner.np.array([(322,124),(311,136),(322,148)],runner.np.int32)],False,(220,220,220),5)
                elif change=='duplicate':
                    for x in (301,319):runner.cv2.polylines(f.image,[runner.np.array([(x,125),(x+8,136),(x,147)],runner.np.int32)],False,(220,220,220),2)
            self.assertIsNone(chapter_navigation_control(f,d,rows),change)
    def test_pending_final_story_is_not_replayed_or_falsely_completed(self):
        f,d,rows=self.fixture();d.update(completion='unconfirmed',clear_badge=False,entry_kind='story_only',cost=0)
        r=fake_runner(f);r.s.update(active=copy.deepcopy(d),attempted={d['key']:copy.deepcopy(d)},entry_dispatches={d['key']:[dict(status='sent')]})
        before=copy.deepcopy(r.s);r.map_ticket=Mock(return_value=(d,rows,'未通关蓝色当前节点'))
        r.story_handoff=Mock();r.story_handoff.step.return_value=None
        r.story_open_ack=Mock();r.story_open_ack.step.return_value=None
        self.assertTrue(self.step(r)[0]);r.action.assert_not_called()
        for key in ('attempted','entry_dispatches','completed'):self.assertEqual(r.s[key],before[key])
    def test_completed_final_active_keeps_history_and_uses_independent_fact(self):
        f,d,rows=self.fixture();r=fake_runner(f)
        old=dict(d,clear_badge=False,completion='unconfirmed',cost=0,entry_kind='story_only')
        r.s.update(active=copy.deepcopy(old),attempted={d['key']:copy.deepcopy(old)},entry_dispatches={d['key']:[dict(status='sent')]})
        original=copy.deepcopy(r.s);r.map_ticket=Mock(return_value=(d,rows,'已通关绿色勾'))
        self.assertTrue(self.step(r)[0]);self.assertIn(d['key'],r.s['completed'])
        for key in ('attempted','entry_dispatches'):self.assertEqual(r.s[key],original[key])
        self.assertEqual(r.action.call_args.args[0],'完成本章后进入下一章')
    def test_no_live_input_when_current_chevron_pixels_or_critical_write_fail(self):
        for failure in ('pixels','save','fixed_xy'):
            f,d,rows=self.fixture();r=fake_runner(f);r.map_ticket=Mock(return_value=(d,rows,'已通关绿色勾'))
            r.ensure_game=Mock();r.adb=Mock();r.save=Mock();target=chapter_navigation_control(f,d,rows)
            if failure=='save':r.save.side_effect=OSError('disk full')
            with patch('ui_control_guard.verify_live_controls',return_value=None if failure=='pixels' else dict(captured_at=time.time())),patch('runner.event'):
                if failure=='save':
                    with self.assertRaises(OSError):runner.Runner._action(r,'完成本章后进入下一章',target)
                else:runner.Runner._action(r,'完成本章后进入下一章',target,xy=(320,137) if failure=='fixed_xy' else None)
            r.adb.assert_not_called()

if __name__=='__main__':unittest.main()
