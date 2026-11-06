import unittest
from unittest.mock import Mock
from test_map_layout import frame
from tutorial_ocr import strengthen_actor

class TutorialOcrTests(unittest.TestCase):
    def make(self):
        f=frame([('护卫队长克劳乌',400,808),('2617/2754',430,859),('X3/3',212,26)])
        f.words[0]['score']=.97;return f
    def test_two_current_exact_high_confidence_reads_strengthen_without_erasing_source(self):
        f=self.make();ocr=Mock(return_value=([(None,'护卫队长克劳乌',.999)],None))
        strengthen_actor(f,ocr);self.assertEqual(ocr.call_count,2);self.assertEqual(f.words[0]['score'],.97)
        self.assertEqual(f.words[-1]['score'],.999);self.assertEqual(f.words[-1]['source'],'current_fixed_actor_roi_dual_read')
    def test_role_score_is_not_rewritten_by_two_verified_identity_suffix_reads(self):
        f=self.make();ocr=Mock(side_effect=[([(None,'护卫队长克劳乌',.96)],None),([['克劳乌',.999]],None),([['克劳乌',.998]],None)])
        strengthen_actor(f,ocr)
        self.assertEqual(f.words[0]['score'],.97);self.assertEqual(f.words[-1]['text'],'克劳乌')
        self.assertEqual(f.words[-1]['score'],.998);self.assertEqual(ocr.call_count,3)
        self.assertEqual(f.words[-1]['source'],'current_fixed_actor_suffix_dual_read')

    def test_low_confidence_disagreement_duplicates_or_missing_context_do_not_strengthen(self):
        for rows in [[(None,'护卫队长克劳乌',.97)],[(None,'其他角色',.999)],[(None,'护卫队长克劳乌',.999)]*2,[]]:
            f=self.make();strengthen_actor(f,Mock(return_value=(rows,None)));self.assertEqual(len(f.words),3)
        f=self.make();f.words.pop();ocr=Mock();strengthen_actor(f,ocr);ocr.assert_not_called()

class OwnedCardLevelTests(unittest.TestCase):
    def current(self):
        f=frame([('准备战斗',148,42),('等级',1318,113),('搜索',1529,118),('维多丽卡',1344,327),('17★',1318,375)])
        f.words[-1]['score']=.822;return f
    def test_same_current_level_double_read_preserves_original_star_merge(self):
        from tutorial_ocr import strengthen_owned_card_level
        f=self.current();ocr=Mock(return_value=([['17',.999]],None));strengthen_owned_card_level(f,ocr)
        self.assertEqual(ocr.call_count,2);self.assertEqual(f.words[-1]['text'],'17');self.assertEqual(f.words[-1]['score'],.999)
        self.assertEqual(f.words[-2]['text'],'17★');self.assertEqual(f.words[-2]['score'],.822)
    def test_disagree_low_duplicate_missing_or_wrong_prefix_never_strengthens(self):
        from tutorial_ocr import strengthen_owned_card_level
        for rows in ([['18',.999]],[['17',.979]],[['17',.999]]*2,[]):
            f=self.current();strengthen_owned_card_level(f,Mock(return_value=(rows,None)));self.assertEqual(len(f.words),5)
        f=self.current();f.words.pop(0);ocr=Mock();strengthen_owned_card_level(f,ocr);ocr.assert_not_called()
        f=self.current();f.words[-1]['text']='★';ocr=Mock();strengthen_owned_card_level(f,ocr);ocr.assert_not_called()

class ChapterThresholdTightTests(unittest.TestCase):
    def current(self):
        f=frame([('第6时代Episode',197,43),('9/15',67,775),('准备战斗',1390,827),('3',205,773),('9',323,773)])
        import cv2
        cv2.rectangle(f.image,(430,764),(435,780),(255,255,255),-1)
        cv2.rectangle(f.image,(442,764),(451,780),(255,255,255),-1)
        return f
    def test_current_tight_digits_recover_low_scoring_whitespace_without_lower_threshold(self):
        from tutorial_ocr import strengthen_chapter_reward_thresholds
        f=self.current();ocr=Mock(side_effect=[([],None),([['15 ',.93]],None),([['15',.999]],None),([['15',.998]],None)])
        strengthen_chapter_reward_thresholds(f,ocr);self.assertEqual(f.words[-1]['text'],'15');self.assertEqual(f.words[-1]['score'],.998)
        self.assertEqual(f.words[-1]['source'],'current_chapter_reward_threshold_tight_dual_read')
    def test_tight_digit_reader_has_no_number_special_case_and_rejects_disagreement_weak_or_missing_shape(self):
        from tutorial_ocr import _tight_chapter_threshold_reads
        self.assertEqual(_tight_chapter_threshold_reads(self.current(),Mock(return_value=([['27',.999]],None)),(425,752,470,794)),[('27',.999)]*2)
        for results in [([['15',.979]],None),([['15 ',.999]],None),([['15',.999],['5',.999]],None)]:
            self.assertEqual(_tight_chapter_threshold_reads(self.current(),Mock(return_value=results),(425,752,470,794)),[])
        f=self.current();f.image[:]=22;ocr=Mock();self.assertEqual(_tight_chapter_threshold_reads(f,ocr,(425,752,470,794)),[]);ocr.assert_not_called()
        ocr=Mock(side_effect=[([['15',.999]],None),([['16',.999]],None)])
        # Caller rejects the unequal dual reads; neither value is appended.
        from tutorial_ocr import strengthen_chapter_reward_thresholds
        f=self.current();ocr=Mock(side_effect=[([],None),([['15 ',.93]],None),([['15',.999]],None),([['16',.999]],None)])
        strengthen_chapter_reward_thresholds(f,ocr);self.assertEqual(len(f.words),5)

class PreparationLabelTests(unittest.TestCase):
    def current(self):
        f=frame([('准备战斗',148,42),('闯关成功',1262,242),('完成故事',1260,278),('1名以上英雄存活',1301,313),('管理队伍',88,860),('进行任务+',1443,830)])
        f.words[-1]['score']=.921;return f
    def test_current_full_single_entry_label_double_read_preserves_original(self):
        from tutorial_ocr import strengthen_preparation_entry_label
        f=self.current();ocr=Mock(return_value=([['进行任务',.997]],None));strengthen_preparation_entry_label(f,ocr)
        self.assertEqual(ocr.call_count,2);self.assertEqual(f.words[-1]['text'],'进行任务');self.assertEqual(f.words[-2]['text'],'进行任务+')
    def test_repeat_wrong_low_ambiguous_missing_anchors_do_not_strengthen(self):
        from tutorial_ocr import strengthen_preparation_entry_label
        for text in ('重新进行','进行任务10次','购买','未知任务'):
            f=self.current();f.words[-1]['text']=text;ocr=Mock();strengthen_preparation_entry_label(f,ocr);ocr.assert_not_called()
        for rows in ([['进行任务',.979]],[['重新进行',.999]],[['进行任务',.999]]*2,[]):
            f=self.current();strengthen_preparation_entry_label(f,Mock(return_value=(rows,None)));self.assertEqual(len(f.words),6)
        for i in range(5):
            f=self.current();f.words.pop(i);ocr=Mock();strengthen_preparation_entry_label(f,ocr);ocr.assert_not_called()

if __name__=='__main__':unittest.main()
