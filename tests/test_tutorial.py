"""Synthetic tutorial policy/dispatch tests; never connect to a device."""
import copy,time,unittest
from unittest.mock import Mock,patch
import runner
from tutorial_core import tutorial_plan,TutorialController,manual_combat_plan,chapter_star_reward_plan

_last_frame_at=0

def frame(extra=()):
    global _last_frame_at
    rows=[('致亲爱的继承者',630,185,.999),('今天，是在全新的舞台一一【原石铸界】迎接继承者的日子。',779,255,.99),('现在，是时候开启新的旅程了。',639,463,.97),('×轻触后关闭',799,868,.91),*extra]
    f=runner.Frame(runner.np.full((900,1600,3),50,runner.np.uint8),[([[x-25,y-12],[x+25,y-12],[x+25,y+12],[x-25,y+12]],t,c) for t,x,y,c in rows])
    _last_frame_at=max(f.at,_last_frame_at+.00001);f.at=_last_frame_at;return f

def controller():
    r=Mock();r.s={};r.evidence.return_value='evidence.png';return r,TutorialController(r)

class TutorialTests(unittest.TestCase):
    def test_complete_free_hero_join_notice_and_unknown_ok_veto(self):
        from test_map_layout import frame as make
        words=[('不成熟的维多丽卡已加入',799,243),('英雄【不成熟的维多丽卡】已加入。',799,504),('将其配置进队伍后，进行战斗吧。',800,533),('OK',800,645)]
        self.assertEqual(tutorial_plan(make(words))['rule'],'hero_joined')
        for index in range(len(words)):
            altered=make(words);altered.words.pop(index);self.assertIsNone(tutorial_plan(altered))
        self.assertEqual(runner.classify(make([('OK',800,645)])),'unknown_dialog')

    def test_pending_chapter_free_milestone_is_not_a_story_entry(self):
        from test_map_layout import frame as make
        im=runner.np.full((900,1600,3),22,runner.np.uint8)
        runner.cv2.circle(im,(158,793),6,(0,100,240),-1)
        words=[('第6时代Episode',197,43),('第1章使徒现身',187,138),('3/9',67,774),('观看故事',1391,827)]
        f=make(words,im);plan=chapter_star_reward_plan(f)
        self.assertEqual(plan['rule'],'chapter_star_reward');self.assertEqual(plan['target']['x'],187)
        self.assertEqual(runner.classify(f),'new_player_tutorial')
        for index in range(len(words)):
            other=make(words,im);other.words.pop(index);self.assertIsNone(chapter_star_reward_plan(other))
        other=make([*words[:2],('0/9',67,774),words[-1]],im);self.assertIsNone(chapter_star_reward_plan(other))
        other=make(words,runner.np.zeros_like(im));self.assertIsNone(chapter_star_reward_plan(other))
        other=make([*words,('取消',800,500)],im);self.assertEqual(runner.classify(other),'unknown_dialog')
        for needed,dot_x,card_x in ((6,282,311),(9,407,436)):
            other_im=runner.np.full_like(im,22);runner.cv2.circle(other_im,(dot_x,793),6,(0,100,240),-1)
            current=make([*words[:2],(str(needed)+'/9',67,774),words[-1]],other_im)
            self.assertEqual(chapter_star_reward_plan(current)['target']['x'],card_x)
            bad=make([*words[:2],('6/6',67,774),words[-1]],other_im)
            self.assertIsNone(chapter_star_reward_plan(bad));self.assertEqual(runner.classify(bad),'chapter_reward_pending')


    def test_manual_basic_requires_hero_hp_wave_ready_skill_and_live_enemy(self):
        from test_map_layout import frame as make
        im=runner.np.full((900,1600,3),22,runner.np.uint8)
        for x in (1230,1360,1490):
            im[780:880,x:x+90]=(0,0,220);im[780:830,x:x+45]=(220,100,0)
        im[735:755,1200:1345]=(240,240,240);im[755:775,1200:1345]=(0,220,240)
        im[418:459,1040:1081]=(0,0,220);im[426:441,1118:1188]=(20,200,60)
        words=[('护卫队长克劳乌',400,808),('2754/2754',430,858),('x 1/2',212,26),('10',1103,439)]
        f=make(words,im);self.assertIsNotNone(manual_combat_plan(f))
        for index in range(len(words)):
            altered=make(words,im.copy());altered.words.pop(index);self.assertIsNone(manual_combat_plan(altered))
        for rect in ((735,775,1200,1345),(418,459,1040,1081),(426,441,1118,1188)):
            y1,y2,x1,x2=rect;altered=make(words,im.copy());altered.image[y1:y2,x1:x2]=0
            self.assertIsNone(manual_combat_plan(altered))
        paid=make([*words,('购买体力',800,450)],im);self.assertEqual(runner.classify(paid),'resource_stop')
        two=im.copy();two[780:880,1490:1580]=0
        v=make([('不成熟的维多丽卡',385,809),*words[1:]],two)
        self.assertIsNotNone(manual_combat_plan(v))
        self.assertIsNotNone(manual_combat_plan(make(words,two)))  # S3 may be passive/absent; verified S1 is still valid.
        guide=make([*words,('请使用第二个技能',800,450)],im)
        self.assertIsNone(manual_combat_plan(guide))
        skip=make([*words,('跳过教学',1450,42)],im)
        self.assertEqual(runner.classify(skip),'tutorial_skip')


    def test_unknown_observation_and_restart_do_not_release_same_page(self):
        r,c=controller();c.step(frame());c.step(frame());c.observe_scene('unknown');c.observe_scene('loading')
        TutorialController(r).step(frame());r.action.assert_called_once()
        c.observe_scene('map');c.step(frame());c.step(frame());self.assertEqual(r.action.call_count,2)

    def test_complete_letter_is_known_before_generic_close_veto(self):
        self.assertEqual(runner.classify(frame()),'new_player_tutorial')
        self.assertEqual(tutorial_plan(frame())['rule'],'welcome_letter')
    def test_incomplete_ambiguous_or_paid_is_not_permitted(self):
        for extra in [[('确认',1300,820,.999)],[('购买',1200,800,.999)],[('×轻触后关闭',800,870,.999)],[('装备已满',800,450,.99)]]:
            self.assertIsNone(tutorial_plan(frame(extra)))
        f=frame();f.words.pop(0);self.assertIsNone(tutorial_plan(f))
        f=frame();f.words[0]['score']=.8;self.assertIsNone(tutorial_plan(f))
    def test_needs_independent_fresh_target_and_durable_intent(self):
        r,c=controller();f=frame();self.assertEqual(c.step(f),(True,.25));r.action.assert_not_called()
        c.step(f);r.action.assert_not_called()
        f=frame();f.at+=.01;snap=[];r.action.side_effect=lambda *a,**k:snap.append(copy.deepcopy(r.s))
        c.step(f);r.action.assert_called_once();self.assertEqual(snap[0]['tutorial']['actions'][0]['status'],'reserved')
        self.assertEqual(r.s['tutorial']['actions'][0]['status'],'sent');c.step(frame());r.action.assert_called_once()
    def test_persistence_or_send_failure_never_replays(self):
        for failure in ('save','action'):
            r,c=controller();c.step(frame());getattr(r,failure).side_effect=OSError('failure')
            with self.assertRaises(OSError):c.step(frame())
            if failure=='save':r.action.assert_not_called()
            else:self.assertEqual(r.s['tutorial']['actions'][0]['status'],'reserved')
    def test_new_controller_does_not_reset_prior_dispatch(self):
        r,c=controller();c.step(frame());c.step(frame());TutorialController(r).step(frame());r.action.assert_called_once()
    def test_target_movement_or_stale_frame_must_reobserve(self):
        r,c=controller();c.step(frame());f=frame();f.words[-1]['x']+=20;c.step(f);r.action.assert_not_called()
        f.at=time.time()-10;c.step(f);r.action.assert_not_called()

if __name__=='__main__':unittest.main()
