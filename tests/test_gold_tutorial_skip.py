"""Gold tutorial text is a verified glyph profile, not a brightness fallback."""
import copy
import unittest
from unittest.mock import patch
import runner
from ui_control_guard import matching_control_pixels
from test_chat_recovery import RecoveryTestCase,make_frame,runner_for


def golden():
    f=make_frame([('跳过教学',1452,42,116)])
    mask=f.image.min(axis=2)>120
    f.image[mask]=(80,170,210)
    return f


class GoldTutorialSkipTests(RecoveryTestCase):
    def preparation(self):
        return make_frame([('跳过教学',1452,42,116),('准备战斗',148,42,128),
            ('进行任务',1438,820,112),('登场的敌人',1269,361,120),('闯关成功',1265,234,100),
            ('可获得的奖励',1263,576,180)])

    def test_full_preparation_objective_does_not_hide_its_free_tutorial_skip(self):
        from task_overlays import top_right_skip_control
        from story_core import team_entry_control
        f=self.preparation();self.assertEqual(runner.classify(f),'tutorial_skip')
        self.assertIsNotNone(top_right_skip_control(f.words,tutorial=True))
        self.assertIsNone(top_right_skip_control(f.words,tutorial=False))
        self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_free_skip_does_not_require_authorizing_the_entry_beneath_its_overlay(self):
        from story_core import team_entry_control
        f=self.preparation();f.words[2]['score']=.94
        self.assertEqual(runner.classify(f),'tutorial_skip')
        self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_incomplete_wrong_position_or_weak_preparation_never_bypasses_result_veto(self):
        from task_overlays import top_right_skip_control
        for change in ('missing','weak','position','extra_result'):
            f=self.preparation()
            if change=='missing':f.words.pop(3)
            elif change=='weak':f.words[1]['score']=.979
            elif change=='position':f.words[4]['y']=550
            else:f.words+=make_frame([('战斗结果',1000,550,100)]).words
            self.assertIsNone(top_right_skip_control(f.words,tutorial=True))

    def test_weak_or_moved_tutorial_still_vetoes_underlying_entry(self):
        from story_core import team_entry_control
        for change in ('weak','position'):
            f=self.preparation()
            if change=='weak':f.words[0]['score']=.5
            else:f.words[0].update(x=500,y=500)
            self.assertEqual(team_entry_control(f)['kind'],'unknown')

    def test_same_verified_gold_control_matches_without_white_pixels(self):
        f=golden();proof=matching_control_pixels(f.image,f.image.copy(),f.words)
        self.assertIsNotNone(proof)
        self.assertEqual(proof[0]['recall'],1)
        self.assertEqual(proof[0]['precision'],1)

    def test_verified_gold_skip_sends_once_without_full_ocr_or_extending_ttl(self):
        f=golden();r=runner_for(f);at=f.at
        r.action('跳过已识别的免费地图教学',f.words[0])
        r.pc.tap.assert_called_once()
        r.capture.assert_not_called();r.ocr.assert_not_called()
        self.assertEqual(r.frame.at,at)

    def test_missing_or_different_gold_glyph_discards_old_target(self):
        for changed in ('missing','different'):
            f=golden();r=runner_for(f);im=f.image.copy();im[20:75,1380:1530]=40
            if changed=='different':runner.cv2.circle(im,(1452,42),15,(80,170,210),2)
            r._capture_pixels.return_value=(im,f.raw_size)
            self.assertIs(r.action('跳过已识别的免费地图教学',f.words[0]),False)
            r.pc.tap.assert_not_called()

    def test_gold_profile_is_not_allowed_for_other_labels_low_ocr_or_other_positions(self):
        for change in ('label','score','position'):
            f=golden();w=copy.deepcopy(f.words[0])
            if change=='label':w['text']='确认'
            elif change=='score':w['score']=.979
            else:
                image=runner.np.full_like(f.image,40);image[300:333,500:616]=f.image[26:59,1394:1510]
                f.image=image;w.update(x=558,y=316,box=[[500,300],[616,300],[616,333],[500,333]])
            self.assertIsNone(matching_control_pixels(f.image,f.image.copy(),[w]))

    def test_stale_gold_source_never_gets_a_new_input_lifetime(self):
        from pc_backend import FrameExpired
        f=golden();r=runner_for(f);f.at-=6
        with self.assertRaises(FrameExpired):r.action('跳过已识别的免费地图教学',f.words[0])
        r._capture_pixels.assert_not_called();r.pc.tap.assert_not_called()

    def test_gold_profile_does_not_weaken_both_confirm_and_cancel_checks(self):
        f=make_frame([('确认',935,575,80),('取消',665,575,80)])
        mask=f.image.min(axis=2)>120;f.image[mask]=(80,170,210)
        self.assertIsNone(matching_control_pixels(f.image,f.image.copy(),f.words))


if __name__=='__main__':unittest.main()
