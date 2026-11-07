"""Game facts are authoritative; sending/timeout/page changes are not outcomes."""
import copy,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import runner
from progression_facts import map_progress_fact
from test_map_layout import map_frame,fake_runner
from test_story_skip_guard import frame

class MapFactTests(unittest.TestCase):
    def fixture(self):
        f=map_frame();r=fake_runner(f);selected,rows,_=r.map_ticket(f)
        entry=dict(selected,start_epoch=time.time()-9999,cost=8)
        return f,r,entry,selected,rows
    def step(self,r):
        with patch.object(runner,'ROOT',Path('no-live-game-fact-test')),patch.object(runner,'event'):
            return r.step(r.frame)
    def test_explicit_current_clear_wins_over_missing_unknown_or_unacknowledged_dispatch(self):
        for dispatch in ([],[dict(status='reserved')],[dict(status='unknown')],[dict(status='sent')]):
            f,r,e,d,rows=self.fixture();rows[0]['completion']='cleared'
            r.s.update(active=e,attempted={e['key']:copy.deepcopy(e)},entry_dispatches={e['key']:dispatch})
            before=copy.deepcopy(r.s['attempted']);r.map_ticket=Mock(return_value=(d,rows,'已通关绿色勾'))
            self.step(r)
            self.assertIn(e['key'],r.s['completed']);self.assertEqual(r.s['attempted'],before)
            self.assertEqual(r.s['entry_dispatches'][e['key']],dispatch)
    def test_original_locked_next_to_current_unlocked_is_progress_without_click_authority(self):
        f,r,e,d,rows=self.fixture();e['progress_before']=dict(key=e['key'],next_locked=True)
        rows[1].update(locked=False,lock_score=.1)
        result=map_progress_fact(f,e,d,rows)
        self.assertTrue(result.completed);self.assertEqual(result.proof['source'],'successor_lock_to_unlock')
    def test_already_unlocked_next_is_not_fictional_completion(self):
        for before in ({},dict(key='foreign',next_locked=True),dict(key='E3-C6-S5',next_locked=False)):
            f,r,e,d,rows=self.fixture();e['progress_before']=before;rows[1].update(locked=False,lock_score=.1)
            self.assertFalse(map_progress_fact(f,e,d,rows).completed)
    def test_foreign_branch_never_credits_old_stage(self):
        f,r,e,d,rows=self.fixture();e['chapter_suffix']='S';rows[0]['completion']='cleared'
        self.assertFalse(map_progress_fact(f,e,d,rows).completed)
    def test_green_pixels_or_sent_click_alone_are_not_a_clear(self):
        f,r,e,d,rows=self.fixture();f.image[240:350,:130]=(0,255,0)
        for row in rows:row.update(completion='unconfirmed',clear_badge=False)
        result=map_progress_fact(f,e,d,rows);self.assertFalse(result.completed);self.assertFalse(result.forward_unlocked)
    def test_forward_selected_unlocked_stage_can_proceed_without_claiming_old_clear(self):
        f,r,e,d,rows=self.fixture();target=dict(d,stage=6,key='E3-C6-S6',cyan=.2,locked=False,lock_score=.1)
        r.map_ticket=Mock(return_value=(target,[dict(target)],'未通关蓝色当前节点'))
        r.s['active']=e;r.s['attempted'][e['key']]=copy.deepcopy(e)
        self.step(r)
        self.assertNotIn(e['key'],r.s['completed']);self.assertIsNone(r.s['active'])
        self.assertEqual(r.s['unresolved_entries'][-1]['entry']['key'],e['key'])
        r.action.assert_called_once();self.assertEqual(r.ticket['key'],target['key'])
    def test_send_only_pending_battle_on_map_never_becomes_failure_or_manual_attention(self):
        f,r,e,d,rows=self.fixture();r.s['active']=e;r.s['attempted'][e['key']]=copy.deepcopy(e)
        for age in (1,30,3600):
            e['start_epoch']=time.time()-age;keep,_=self.step(r);self.assertTrue(keep)
            self.assertEqual(r.s['completed'],{});self.assertFalse(r.s.get('terminal',False))
            self.assertNotIn('attention',r.s);self.assertEqual(r.s.get('stage_outcomes',[]),[])
        r.action.assert_not_called()
    def test_history_only_without_current_clear_observes_not_failure(self):
        f,r,e,d,rows=self.fixture();r.s['attempted'][e['key']]=copy.deepcopy(e)
        self.assertTrue(self.step(r)[0]);self.assertNotIn('attention',r.s);r.action.assert_not_called()
    def test_next_locked_after_current_clear_is_observation_not_failure(self):
        f,r,e,d,rows=self.fixture();rows[1].update(locked=True,lock_score=.99)
        r.map_ticket=Mock(return_value=(d,rows,'已通关关卡星级'))
        self.assertTrue(self.step(r)[0]);self.assertNotIn('attention',r.s);r.action.assert_not_called()
    def test_pending_free_story_still_uses_proven_reward_navigation_handoff(self):
        f,r,e,d,rows=self.fixture();e.update(entry_kind='story_only',cost=0)
        r.s['active']=e;r.s['attempted'][e['key']]=copy.deepcopy(e)
        r.story_handoff=Mock();r.story_handoff.step.return_value=(True,.25)
        r.story_open_ack=Mock();r.story_open_ack.step.return_value=None
        self.assertTrue(self.step(r)[0]);r.story_handoff.step.assert_called_once_with(f)
        r.story_open_ack.step.assert_not_called();r.action.assert_not_called()
        self.assertEqual(r.s['completed'],{});self.assertNotIn('stage_outcomes',r.s)

    def test_clear_result_close_is_not_itself_a_completion(self):
        f,r,e,d,rows=self.fixture()
        r.frame=frame([('获得的道具',1380,95),('战斗结果',1240,835),('确认',1460,835)])
        r.s['active']=e;r.s['attempted'][e['key']]=copy.deepcopy(e)
        self.assertEqual(runner.classify(r.frame),'settlement');self.assertTrue(self.step(r)[0])
        self.assertEqual(r.s['completed'],{});self.assertIsNotNone(r.s['active'])
        self.assertIn('settlement_observed',r.s['active']);r.action.assert_called_once()
    def test_only_explicit_defeat_records_defeat(self):
        f,r,e,d,rows=self.fixture();r.frame=frame([('FAILED',800,250)])
        r.s['active']=e;r.s['attempted'][e['key']]=copy.deepcopy(e)
        self.assertFalse(self.step(r)[0]);self.assertEqual(r.s['stage_outcomes'][-1]['outcome'],'defeat')
        self.assertEqual(r.s['completed'],{});r.action.assert_not_called()

if __name__=='__main__':unittest.main()
