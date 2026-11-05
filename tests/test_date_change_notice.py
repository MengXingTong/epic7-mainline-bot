"""Date-change interruption: synthetic observations only, no native input."""
import copy
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import runner
from task_overlays import date_change_notice_close


NOTICE = [('变更日期', 800, 270), ('日期变更，将前往大厅。', 802, 448), ('点击关闭', 802, 599)]


def frame(words):
    rows = [([[x-20,y-10],[x+20,y-10],[x+20,y+10],[x-20,y+10]],text,.99) for text,x,y in words]
    return runner.Frame(runner.np.full((900,1600,3),50,runner.np.uint8),rows)


class DateChangeNoticeTests(unittest.TestCase):
    def test_reported_layout_selects_only_its_observed_close(self):
        f = frame(NOTICE)
        self.assertEqual(runner.classify(f), 'date_change_notice')
        self.assertIs(date_change_notice_close(f.words), f.words[-1])

    def test_missing_low_confidence_or_moved_anchor_never_clicks_through_map(self):
        background = [('Episode 4',155,44),('准备战斗',1400,825)]
        for index in range(3):
            for change in ('missing','confidence','position'):
                with self.subTest(index=index,change=change):
                    f = frame(NOTICE+background)
                    if change=='missing':f.words.pop(index)
                    elif change=='confidence':f.words[index]['score']=.6
                    else:f.words[index]['x']=50
                    self.assertIsNone(date_change_notice_close(f.words))
                    self.assertEqual(runner.classify(f),'unknown_dialog')

    def test_unknown_confirmation_paid_or_capacity_overlay_vetoes_close(self):
        for extra, expected in [('确认','unknown_dialog'),('取消','unknown_dialog'),
                                ('购买体力','resource_stop'),('装备背包已满','capacity_stop'),('战斗失败','defeat')]:
            f=frame(NOTICE+[(extra,800,450)])
            self.assertEqual(runner.classify(f),expected)
        for extra in ('确认','取消','购买','兑换','复活','是否使用道具','战斗失败','FAILED'):
            self.assertIsNone(date_change_notice_close(frame(NOTICE+[(extra,800,450)]).words))

    def test_duplicate_or_displaced_close_is_not_replaced_by_a_fixed_coordinate(self):
        for closing in [('点击关闭',900,620),('点击关闭',1450,825),('点击关闭',800,80)]:
            self.assertIsNone(date_change_notice_close(frame(NOTICE+[closing]).words))
        f=frame(NOTICE);f.words[-1]['y']=80
        self.assertIsNone(date_change_notice_close(f.words))

    def test_dismissal_preserves_unsettled_entries_and_clears_only_navigation_ticket(self):
        r=runner.Runner.__new__(runner.Runner)
        r.last_mode=None;r.mode_since=time.time();r.unknown_gestures=0;r.ticket={'key':'planned'}
        r.s={'active':{'key':'pending'},'attempted':{'pending':{'keep':True}},'completed':{},
             'last_cleared':{'key':'older'},'unresolved_entries':[{'entry':{'key':'archived'}}]}
        before=copy.deepcopy(r.s);r.action=Mock();r.save=Mock()
        with patch.object(runner,'ROOT',Path('no-live-state-test')),patch('runner.event'):
            keep,_=r.step(frame(NOTICE))
        self.assertTrue(keep);r.action.assert_called_once()
        target=r.action.call_args.args[1]
        self.assertEqual((target['x'],target['y']),(802,599));self.assertIsNone(r.ticket)
        for key in before:self.assertEqual(r.s[key],before[key])


if __name__=='__main__':unittest.main()
