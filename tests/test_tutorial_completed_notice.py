"""Known passive notifications: semantic recognition, per-appearance dismissal."""
import copy,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import runner
from task_overlays import tutorial_completed_notice_close,passive_free_notice
from free_notices import FreeNoticeController,notice_modal_band_visible
from test_story_only_nodes import fake_runner
from test_date_change_notice import frame
from task_blockers import TaskAttention
from pc_backend import TapNotSent
KEY='tutorial_complete.already_completed_tutorial'
def notice(body=KEY):return frame([(body,800,406),('点击关闭',802,555)])

class TutorialCompletedNoticeTests(unittest.TestCase):
    def make_runner(self):
        r=fake_runner(notice());r.run_id='same-run';r.s['active']=dict(key='original-stage',entry_kind='story_only',cost=0)
        r.attention=Mock(side_effect=lambda *a:(_ for _ in ()).throw(TaskAttention(*a)))
        r.free_notices=FreeNoticeController(r);return r
    def fresh(self,r,offset=0,body=KEY):
        f=notice(body);f.at=time.time()+offset;r.frame=f;return f
    def pair(self,r):
        r.free_notices.step(self.fresh(r,-.25));return r.free_notices.step(self.fresh(r))
    def depart(self,r,scene='map'):
        r.free_notices.observe_scene(scene,self.fresh(r,-.25));r.free_notices.observe_scene(scene,self.fresh(r))
    def test_exact_current_unique_high_confidence_close(self):
        f=notice();self.assertIs(tutorial_completed_notice_close(f.words),f.words[-1]);self.assertEqual(runner.classify(f),'tutorial_completed_notice')
    def test_background_narrative_confirmation_is_not_a_confirm_button(self):
        for text in ('好不容易登陆海岸的梅丽莎确认自己回到了故乡','他确定了方向','她取消了约定'):
            f=notice();f.words+=frame([(text,1347,190)]).words
            self.assertEqual(runner.classify(f),'tutorial_completed_notice');self.assertIsNotNone(passive_free_notice(f.words))
    def test_explicit_known_language_variants_not_unknown_error_namespaces(self):
        for body in (KEY,'该教学已完成。','此教程已完成。','tutorial_complete . already_completed_tutorial'):
            self.assertIsNotNone(passive_free_notice(notice(body).words))
        for body in ('tutorial_complete.unknown_error','payment.already_paid','unknown.already_completed_tutorial',KEY[:-1]):
            self.assertIsNone(passive_free_notice(notice(body).words))
    def test_partial_weak_moved_and_duplicated_notice_never_clicks(self):
        for field in (0,1):
            for mode in ('missing','weak','moved','duplicate'):
                with self.subTest(field=field,mode=mode):
                    f=notice()
                    if mode=='missing':f.words.pop(field)
                    if mode=='weak':f.words[field]['score']=.979
                    if mode=='moved':f.words[field]['y']=50
                    if mode=='duplicate':f.words.append(copy.deepcopy(f.words[field]))
                    self.assertIsNone(tutorial_completed_notice_close(f.words))
    def test_unknown_text_fee_failure_capacity_and_confirm_veto(self):
        for text in ('未知说明','确认','取消','购买体力','是否使用道具','战斗失败','装备背包已满'):
            with self.subTest(text=text):
                f=notice();f.words+=frame([(text,800,450)]).words
                self.assertIsNone(tutorial_completed_notice_close(f.words));self.assertNotEqual(runner.classify(f),'tutorial_completed_notice')
        f=notice();f.words+=frame([('确认',1400,825)]).words
        self.assertIsNone(tutorial_completed_notice_close(f.words))
    def test_two_independent_frames_close_durably_without_completing_or_retrying_stage(self):
        r=self.make_runner();snapshots=[];r.action.side_effect=lambda *a:snapshots.append(copy.deepcopy(r.s));before=copy.deepcopy(r.s['active'])
        with patch('runner.event'),patch.object(runner,'ROOT',Path('synthetic-nonexistent')):
            r.step(self.fresh(r,-.25));r.action.assert_not_called();r.step(self.fresh(r));r.action.assert_called_once()
        self.assertEqual(r.s['completed'],{});self.assertEqual(r.s['active'],before)
        self.assertEqual(snapshots[0]['free_notice_dismissals']['occurrences'][0]['messages'][0]['status'],'reserved')
    def test_worker_runner_same_frame_is_not_a_second_disappearance_or_duplicate_evidence(self):
        r=self.make_runner();self.pair(r);f=self.fresh(r);r.free_notices.observe_scene('map',f)
        count=r.evidence.call_count
        r.free_notices.observe_scene('map',f)
        self.assertEqual(r.evidence.call_count,count);self.assertIsNotNone(r.free_notices.active())
        r.free_notices.observe_scene('map',self.fresh(r,.001));self.assertIsNone(r.free_notices.active())
        record=r.s['free_notice_dismissals']['occurrences'][0]
        self.assertEqual(len(record['disappearance_observations']),2)
        self.assertLess(record['disappearance_observations'][0]['captured_at'],record['disappearance_observations'][1]['captured_at'])

    def test_same_notice_does_not_double_click_before_ack_window(self):
        r=self.make_runner();self.pair(r);self.pair(r);self.assertEqual(r.action.call_count,1)
    def test_dropped_close_has_fresh_bounded_resend_not_permanent_stage_latch(self):
        r=self.make_runner();self.pair(r);record=r.free_notices.active();record['messages'][0]['finished_at']-=4
        self.pair(r);self.assertEqual(r.action.call_count,2)
        self.assertEqual(len(r.s['free_notice_dismissals']['occurrences']),1)
        self.assertNotEqual(record['messages'][0]['id'],record['messages'][1]['id'])
    def test_same_unresponsive_notice_stops_after_three_distinct_close_intents(self):
        r=self.make_runner()
        for i in range(3):
            self.pair(r);r.free_notices.active()['messages'][-1]['finished_at']-=4
        with self.assertRaises(TaskAttention):self.pair(r)
        self.assertEqual(r.action.call_count,3)
    def test_reappearing_same_notice_and_same_no_stage_context_closes_again(self):
        r=self.make_runner();r.s['active']=None;r.s['tutorial_completed_notice_closes']={'same-run:None':dict(status='sent',evidence='old.png')}
        old=copy.deepcopy(r.s['tutorial_completed_notice_closes']);self.pair(r);self.depart(r)
        self.assertIsNone(r.free_notices.active());self.pair(r)
        self.assertEqual(r.action.call_count,2);self.assertEqual(len(r.s['free_notice_dismissals']['occurrences']),2)
        self.assertEqual(r.s['tutorial_completed_notice_closes'],old);self.assertEqual(r.s['completed'],{})
    def test_new_occurrences_have_no_global_run_or_stage_count_cap(self):
        r=self.make_runner()
        for i in range(5):self.pair(r);self.depart(r)
        self.assertEqual(r.action.call_count,5);self.assertEqual(len(r.s['free_notice_dismissals']['occurrences']),5)
    def test_unknown_loading_and_single_absence_do_not_rearm(self):
        for scene in ('unknown','unknown_dialog','loading','result_transition','capacity_stop','resource_stop','defeat'):
            r=self.make_runner();self.pair(r);first=r.free_notices.active()['id'];self.depart(r,scene)
            self.assertEqual(r.free_notices.active()['id'],first);self.pair(r);r.action.assert_called_once()
        r=self.make_runner();self.pair(r);r.free_notices.observe_scene('map',self.fresh(r));self.assertIsNotNone(r.free_notices.active())
    def test_modal_chrome_still_visible_is_not_a_disappearance(self):
        r=self.make_runner();self.pair(r)
        for offset in (-.25,0):
            f=self.fresh(r,offset);f.image[254:256,:]=180;f.image[644:646,:]=180
            self.assertTrue(notice_modal_band_visible(f.image));r.free_notices.observe_scene('map',f)
        self.assertIsNotNone(r.free_notices.active());self.pair(r);r.action.assert_called_once()
    def test_target_moves_stale_reused_and_detached_frames_never_close(self):
        r=self.make_runner();f=self.fresh(r,-4);r.free_notices.step(f);r.action.assert_not_called()
        f=self.fresh(r,-.25);r.free_notices.step(f);r.free_notices.step(f);r.action.assert_not_called()
        f=self.fresh(r);f.words[-1]['x']+=20;r.free_notices.step(f);r.action.assert_not_called()
        r.free_notices.step(notice());r.action.assert_not_called()
    def test_restart_preserves_active_occurrence_and_original_message_count(self):
        r=self.make_runner();self.pair(r);r.free_notices=FreeNoticeController(r);self.pair(r)
        r.action.assert_called_once();self.assertEqual(len(r.s['free_notice_dismissals']['occurrences']),1)
    def test_explicit_new_run_keeps_old_occurrence_without_borrowing_entry_permission(self):
        r=self.make_runner();self.pair(r);r.run_id='new-explicit-run';r.free_notices=FreeNoticeController(r);self.pair(r)
        self.assertEqual(r.action.call_count,2);self.assertEqual(len(r.s['free_notice_dismissals']['occurrences']),2)
        self.assertEqual(r.s['free_notice_dismissals']['occurrences'][0]['phase'],'superseded_by_explicit_new_run')
    def test_save_and_evidence_failure_prevent_input(self):
        for target in ('save','evidence'):
            r=self.make_runner();getattr(r,target).side_effect=OSError('denied')
            with self.assertRaises(OSError):self.pair(r)
            r.action.assert_not_called();self.assertEqual(r.s['completed'],{})
    def test_send_failure_never_relabels_original_entry_or_reuses_intent(self):
        for exc in (OSError('unknown'),TapNotSent('before down')):
            r=self.make_runner();r.s['attempted']={'original':{'keep':True}};before=copy.deepcopy(r.s['attempted']);r.action.side_effect=exc
            with self.assertRaises(type(exc)):self.pair(r)
            self.pair(r);r.action.assert_called_once();self.assertEqual(r.s['attempted'],before);self.assertEqual(r.s['completed'],{})
            self.assertIn(r.free_notices.active()['messages'][0]['status'],('unknown','not_sent'))
if __name__=='__main__':unittest.main()
