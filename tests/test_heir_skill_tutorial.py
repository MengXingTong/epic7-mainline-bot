"""Forced heir tutorial controls and source-linked one-use skill stages."""
import copy,time,unittest
from unittest.mock import Mock,patch
import runner
from task_blockers import TaskAttention
from test_map_layout import frame
from tutorial_core import tutorial_plan,TutorialController

COMMON=[('维多丽卡',444,808),('1890/1890',430,858),('x 3/3',212,26),('倪尔伽',427,21),('Lv.10',998,24)]


def teaching(kind):
    f=frame(COMMON)
    if kind=='arrival':
        f.words.extend(frame([('成为继承者的维多丽卡登场',834,648)]).words)
        f.image[575:590,600:1060]=(220,150,20)
    elif kind=='skill':
        f.words.extend(frame([('使用全新技能进行攻击',1205,808)]).words)
        f.image[715:780,1415:1600]=(220,150,20)
        f.image[780:880,1490:1580]=(0,0,220);f.image[780:830,1490:1535]=(220,100,0)
    elif kind=='tooltip':
        f.words.extend(frame([('承诺的荣耀',1155,480),('冲锋攻击敌人，并使全体我军人员在2回',1180,576),('合内获得免疫效果。根据目标最大生命值',1185,603)]).words)
        f.image[260:410,1200:1350]=(160,160,160)
    elif kind=='execute':
        f.image[735:755,1460:1599]=(240,240,240);f.image[755:775,1460:1599]=(0,220,240)
        f.image[300:450,940:1150]=(160,160,160);f.image[500:650,1200:1300]=(30,180,70)
    time.sleep(.002);return f


def dispatch(c,kind):
    c.step(teaching(kind));return c.step(teaching(kind))


class HeirSkillTutorialTests(unittest.TestCase):
    def test_all_observed_steps_require_their_own_instruction_or_selected_control(self):
        expected={'arrival':'heir_victoria_arrival','skill':'heir_victoria_new_skill','tooltip':'heir_victoria_new_skill_target','execute':'heir_victoria_new_skill_execute'}
        for kind,rule in expected.items():
            self.assertEqual(tutorial_plan(teaching(kind))['rule'],rule)
            for invalid in ('hero','hp','paid','capacity'):
                f=teaching(kind)
                if invalid=='hero':f.words[0]['text']='unknown'
                elif invalid=='hp':f.words.pop(1)
                elif invalid=='paid':f.words.extend(frame([('购买',800,400)]).words)
                else:f.words.extend(frame([('装备背包已满',800,400)]).words)
                self.assertIsNone(tutorial_plan(f),(kind,invalid))

    def test_missing_or_weak_step_instruction_never_infers_a_tap(self):
        for kind in ('arrival','skill','tooltip'):
            f=teaching(kind);f.words[-1]['score']=.979
            self.assertIsNone(tutorial_plan(f))
        f=teaching('execute');f.image[735:775,1460:1599]=22;self.assertIsNone(tutorial_plan(f))

    def controller(self):
        r=Mock();r.ticket=None;r.s={'active':dict(key='stage',start_epoch=time.time()-100)};r.evidence.return_value='offline'
        r.attention.side_effect=lambda code,title,reason:(_ for _ in ()).throw(TaskAttention(code,title,reason))
        return r,TutorialController(r)

    def test_complete_selected_skill_tooltip_close_then_enemy_selection_each_once(self):
        r,c=self.controller();dispatch(c,'skill');self.assertEqual(r.action.call_count,1)
        dispatch(c,'tooltip');self.assertEqual(r.action.call_count,2)
        dispatch(c,'execute');self.assertEqual(r.action.call_count,3)
        source=r.s['tutorial']['actions'][0]
        self.assertEqual(source['enemy_selection']['status'],'sent');self.assertEqual(source['body_selection']['status'],'sent')
        c=TutorialController(r)
        for _ in range(3):dispatch(c,'execute')
        self.assertEqual(r.action.call_count,3)

    def test_no_source_or_unknown_tooltip_close_does_not_click_enemy(self):
        for bad in ('no_source','unknown_source','unknown_close'):
            r,c=self.controller()
            if bad!='no_source':dispatch(c,'skill');r.action.reset_mock()
            if bad=='unknown_source':r.s['tutorial']['actions'][0]['status']='reserved'
            if bad=='unknown_close':r.s['tutorial']['actions'][0]['enemy_selection']=dict(status='reserved')
            with self.assertRaises(TaskAttention):dispatch(c,'execute' if bad=='unknown_close' else 'tooltip')
            r.action.assert_not_called()

    def test_unknown_body_send_remains_consumed_across_controller_restart(self):
        r,c=self.controller();dispatch(c,'skill');dispatch(c,'tooltip');r.action.side_effect=RuntimeError('unknown')
        with self.assertRaises(RuntimeError):dispatch(c,'execute')
        r.action.side_effect=None;r.action.reset_mock();dispatch(TutorialController(r),'execute');r.action.assert_not_called()
        self.assertEqual(r.s['tutorial']['actions'][0]['body_selection']['status'],'reserved')

class FreeHeroDisplayTests(unittest.TestCase):
    def current(self,dialogue=False):
        words=[('维多丽卡',164,112),('火焰属性',129,49),('骑士',240,49),('狮子座',326,50),
               ('详细信息',193,252),('内心住着暴徒的贵族大小姐',179,192),('确认',1418,826)]
        if dialogue:words += [('绝不容忍任何不公，要时刻坚守正义与信念。',800,754),('维多丽卡',802,666)]
        f=frame(words)
        if not dialogue:f.image[795:860,1280:1550]=(35,65,100)
        return f

    def test_dialogue_is_not_dim_confirmation_and_final_confirm_requires_button_body(self):
        from tutorial_core import free_victoria_acquisition_plan
        self.assertEqual(free_victoria_acquisition_plan(self.current(True))['rule'],'free_victoria_acquisition_dialogue')
        self.assertEqual(free_victoria_acquisition_plan(self.current())['rule'],'free_victoria_acquisition_confirm')
        f=self.current();f.image[795:860,1280:1550]=22;self.assertIsNone(free_victoria_acquisition_plan(f))
        for i in range(len(self.current().words)):
            f=self.current();f.words.pop(i);self.assertIsNone(free_victoria_acquisition_plan(f))
        f=self.current();f.words.extend(frame([('购买',800,400)]).words);self.assertIsNone(tutorial_plan(f))

    def test_unknown_hero_display_without_original_skill_clear_chain_never_confirms(self):
        r=Mock();r.s={'tutorial':{'actions':[]}};r.ticket=None
        r.attention.side_effect=lambda code,title,reason:(_ for _ in ()).throw(TaskAttention(code,title,reason))
        with self.assertRaises(TaskAttention):TutorialController(r).step(self.current())
        r.action.assert_not_called()


class GuidedTagTests(unittest.TestCase):
    def current(self):
        f=frame([('通过标签更换英雄',479,810),('TAG',170,852),('倪尔伽',427,21),('1/1',212,26),
                 ('10',300,200),('10',505,311)])
        f.image[725:900,0:250]=(220,150,20)
        return f

    def test_tag_teaching_uses_current_instruction_circle_hud_and_two_allied_levels(self):
        f=self.current();p=tutorial_plan(f);self.assertEqual(p['rule'],'guided_tag_swap')
        self.assertEqual((p['target']['x'],p['target']['y']),(115,825))
        for i in range(len(f.words)):
            bad=self.current();bad.words.pop(i);self.assertIsNone(tutorial_plan(bad))
        bad=self.current();bad.image[725:900,0:250]=22;self.assertIsNone(tutorial_plan(bad))


class LobbyFreeOverlayTests(unittest.TestCase):
    def test_attendance_and_known_promo_close_only_their_own_confirm(self):
        examples=[
          ([('梅露铃的签到奖励',563,97),('签到奖励一天可获得一次。',562,147),('连续签到第1天',1344,700),('获得的奖励：1/28',1344,751),('确认',1340,830)],'melurin_attendance_ack'),
          ([('萌新玩家签到活动',298,80),('连续签到奖励',1318,190),('所有签到奖励将发送至邮箱，领取所有奖励后活动页面将不再显示。',442,782),('因等级不足而未能获得的奖励，将在达成所限等级之后一并发放。',431,806),('确认',1316,788)],'beginner_attendance_ack'),
          ([('兔女郎名侦探莱萝',400,209),('自由奔放的名侦探',409,427),('NEW!',629,301),('盗贼',351,128),('光明属性',479,129),('立即前往召唤',1429,736),('确认',1429,826)],'dismiss_observed_summon_promo'),
          ([('欧勒毕斯指南',800,232),('欧勒毕斯指南功能已开启。',798,497),('可帮助继承者更好地了解《第七史诗》。',801,521),('点击关闭',802,652)],'orbis_guide_unlocked')]
        for words,rule in examples:
            p=tutorial_plan(frame(words));self.assertEqual(p['rule'],rule)
            self.assertIn(p['target']['text'],('确认','点击关闭'))
            for i in range(len(words)):
                bad=frame(words);bad.words.pop(i);self.assertIsNone(tutorial_plan(bad),(rule,i))
            bad=frame(words+[('购买体力',800,400)]);self.assertIsNone(tutorial_plan(bad))


if __name__=='__main__':unittest.main()
