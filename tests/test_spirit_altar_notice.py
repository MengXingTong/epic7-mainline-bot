import copy,time,unittest
from unittest.mock import Mock
from test_map_layout import frame
from tutorial_core import tutorial_plan,TutorialController
from tutorial_ocr import strengthen_spirit_altar_purpose


def current():
    return frame([('精灵祭坛',800,233),('可进入精灵祭坛。',799,497),('请采集可用于英雄觉醒',800,522),('的各种符文！',803,547),('点击关闭',802,653)])


class SpiritAltarNoticeTests(unittest.TestCase):
    def test_complete_free_notice_and_each_missing_or_weak_field(self):
        p=tutorial_plan(current());self.assertEqual(p['rule'],'spirit_altar_unlocked');self.assertEqual(p['target']['text'],'点击关闭')
        for i in range(5):
            for mode in ('missing','weak','duplicate','shift'):
                f=current()
                if mode=='missing':f.words.pop(i)
                elif mode=='weak':f.words[i]['score']=.979
                elif mode=='duplicate':f.words.append(copy.deepcopy(f.words[i]))
                else:f.words[i]['x']=100
                self.assertIsNone(tutorial_plan(f),(i,mode))
        for text in ('购买','是否消耗','战斗失败','装备背包已满','确认'):
            f=current();f.words+=frame([(text,800,400)]).words;self.assertIsNone(tutorial_plan(f))
    def test_exact_awakening_feature_notice_closes_only_not_awakens(self):
        words=[('英雄觉醒',800,231),('可进行英雄觉醒。',797,496),('请使用属性相符的各种符文，',801,522),('使英雄成长变得更强！',803,547),('点击关闭',802,653)]
        p=tutorial_plan(frame(words));self.assertEqual(p['rule'],'hero_awakening_unlocked');self.assertEqual(p['target']['text'],'点击关闭')
        for i in range(5):
            f=frame(words);f.words.pop(i);self.assertIsNone(tutorial_plan(f),i)
            f=frame(words);f.words[i]['score']=.979;self.assertIsNone(tutorial_plan(f),i)
        self.assertIsNone(tutorial_plan(frame(words+[('是否消耗符文',800,400)])))
    def test_exact_bond_notice_is_only_a_free_close(self):
        words=[('缘分',800,233),('现在可以结下缘分了。',799,497),('请通过缘分得到新英雄，',800,522),('并配置到队伍中吧！',804,547),('点击关闭',802,653)]
        p=tutorial_plan(frame(words));self.assertEqual(p['rule'],'bond_feature_unlocked');self.assertEqual(p['target']['text'],'点击关闭')
        for i in range(5):
            f=frame(words);f.words.pop(i);self.assertIsNone(tutorial_plan(f),i)
            f=frame(words);f.words[i]['score']=.979;self.assertIsNone(tutorial_plan(f),i)
        self.assertIsNone(tutorial_plan(frame(words+[('是否消耗英雄',800,400)])))
    def test_original_weak_word_is_preserved_two_independent_purpose_reads(self):
        f=current();f.words[2].update(text='请朵集可用于英雄觉醒',score=.976)
        ocr=Mock(side_effect=[([['可用于英雄觉醒',.996]],None),([['可用于英雄觉醒',.997]],None)])
        strengthen_spirit_altar_purpose(f,ocr);self.assertEqual(ocr.call_count,2)
        self.assertEqual(f.words[2]['score'],.976);self.assertEqual(f.words[2]['text'],'请朵集可用于英雄觉醒')
        self.assertEqual(f.words[-1]['score'],.996);self.assertEqual(tutorial_plan(f)['rule'],'spirit_altar_unlocked')
    def test_wrong_weak_ambiguous_or_missing_context_never_strengthens(self):
        for rows in ([],[['错误',.999]],[['可用于英雄觉醒',.979]],[['可用于英雄觉醒',.999]]*2):
            f=current();f.words[2].update(text='请朵集可用于英雄觉醒',score=.976)
            strengthen_spirit_altar_purpose(f,Mock(return_value=(rows,None)));self.assertEqual(len(f.words),5);self.assertIsNone(tutorial_plan(f))
        f=current();f.words[2].update(text='请朵集可用于英雄觉醒',score=.976);f.words.pop(0);ocr=Mock()
        strengthen_spirit_altar_purpose(f,ocr);ocr.assert_not_called()
        f=current();f.words[2].update(text='购买觉醒材料',score=.99);ocr=Mock();strengthen_spirit_altar_purpose(f,ocr);ocr.assert_not_called()
    def test_purpose_without_current_crop_provenance_is_not_a_free_close(self):
        f=current();f.words[2].update(text='可用于英雄觉醒',x=838);self.assertIsNone(tutorial_plan(f))
    def test_double_frame_once_and_no_progress_claim(self):
        r=Mock();r.s={'active':None,'completed':{'old':{}},'attempted':{'old':{}}};r.evidence.return_value='synthetic'
        c=TutorialController(r);c.step(current());r.action.assert_not_called();c.step(current());r.action.assert_called_once()
        TutorialController(r).step(current());r.action.assert_called_once();self.assertEqual(r.s['completed'],{'old':{}});self.assertEqual(r.s['attempted'],{'old':{}})

if __name__=='__main__':unittest.main()
