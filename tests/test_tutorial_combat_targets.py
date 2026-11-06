"""Synthetic combat targets and same-turn completion, never live inputs."""
import copy,time,unittest
from unittest.mock import Mock,patch
import runner
from test_map_layout import frame
from tutorial_core import plant_enemy_body,TutorialController,manual_combat_plan
from tutorial_ocr import strengthen_enemy_levels


def plant_frame():
    im=runner.np.full((900,1600,3),22,runner.np.uint8)
    im[504:594,1068:1223]=(20,160,50)
    im[594:679,1103:1176]=(30,70,110)
    return frame([],im)


def plan(body=False):
    target=dict(text='body' if body else 'old suspended point',x=1138.,y=637. if body else 519.,score=1.)
    if body:target['source']='current_forest_plant_crown_and_trunk'
    return dict(rule='krau_story_basic',label='basic',target=target,proof=[
        dict(text='护卫队长克劳乌',x=400,y=808,score=.999),dict(text='100/100',x=430,y=858,score=.999),
        dict(text='1/2',x=212,y=26,score=.99),dict(text='10',x=1103,y=439,score=.999),dict(text='ready',x=1270,y=820,score=1.)])


def tick():
    f=frame();time.sleep(.002);return f


def apply(c,p):
    with patch('tutorial_core.tutorial_plan',return_value=p):return c.step(tick())


class CombatTargetTests(unittest.TestCase):
    def test_live_plant_uses_unique_current_trunk_not_hp_plus_80(self):
        f=plant_frame();p=plant_enemy_body(f,dict(x=1103,y=439))
        self.assertIsNotNone(p);self.assertTrue(1103<=p['x']<1176);self.assertTrue(594<=p['y']<679)
        for rect in ((504,594,1068,1223),(594,679,1103,1176)):
            bad=plant_frame();y1,y2,x1,x2=rect;bad.image[y1:y2,x1:x2]=22
            self.assertIsNone(plant_enemy_body(bad,dict(x=1103,y=439)))
        self.assertIsNone(plant_enemy_body(f,dict(x=500,y=439)))

    def test_low_body_and_generic_enemy_targets_cannot_intersect_skill_bar(self):
        f=plant_frame();f.image[640:730,1068:1223]=(20,160,50);f.image[730:815,1103:1176]=(30,70,110)
        self.assertIsNone(plant_enemy_body(f,dict(x=1103,y=575)))

    def test_old_skillbar_mistarget_can_finish_once_on_fresh_verified_enemy(self):
        r=Mock();r.s={};r.ticket=None;r.evidence.return_value='offline';c=TutorialController(r)
        bad=plan();bad['target']['y']=787
        apply(c,bad);apply(c,bad);old=r.s['tutorial']['actions'][0];old['at']=time.time()-10
        apply(c,bad);apply(c,bad)
        current=plan();current['target']['y']=710
        apply(c,current);apply(c,current)
        self.assertEqual(old['corrected_enemy_selection']['status'],'sent');self.assertEqual(r.action.call_count,3)
        for _ in range(3):apply(c,current)
        self.assertEqual(r.action.call_count,3)

    def test_same_turn_skill_then_corrected_trunk_each_sends_once_and_survives_reload(self):
        r=Mock();r.s={};r.ticket=None;r.evidence.return_value='offline'
        c=TutorialController(r);apply(c,plan());apply(c,plan());self.assertEqual(r.action.call_count,1)
        old=r.s['tutorial']['actions'][0];old['at']=time.time()-10
        apply(c,plan());apply(c,plan());self.assertEqual(r.action.call_count,2)
        self.assertEqual(old['basic_skill_selection']['status'],'sent')
        apply(c,plan(True));apply(c,plan(True));self.assertEqual(r.action.call_count,3)
        self.assertEqual(old['corrected_enemy_selection']['status'],'sent')
        self.assertEqual(r.s['tutorial']['combat_latch'],0)
        c=TutorialController(r)
        for _ in range(4):apply(c,plan(True))
        self.assertEqual(r.action.call_count,3)

    def test_same_actor_next_wave_requires_two_new_frames_and_can_then_attack(self):
        r=Mock();r.s={};r.ticket=None;r.evidence.return_value='offline';c=TutorialController(r)
        old=plan();old['proof'][2]['text']='1/3';apply(c,old);apply(c,old)
        current=plan();current['proof'][2]['text']='2/3';apply(c,current)
        self.assertEqual(r.action.call_count,1)
        for _ in range(4):apply(c,current)
        self.assertEqual(r.action.call_count,2)
        self.assertIn('波次',r.s['tutorial']['actions'][0]['turn_transition']['reason'])

    def test_failed_skill_or_correction_never_replays(self):
        for stage in ('skill','body'):
            r=Mock();r.s={};r.ticket=None;r.evidence.return_value='offline';c=TutorialController(r)
            apply(c,plan());apply(c,plan());old=r.s['tutorial']['actions'][0];old['at']=time.time()-10
            if stage=='body':apply(c,plan());apply(c,plan())
            p=plan(stage=='body');apply(c,p);r.action.side_effect=RuntimeError('unknown')
            with self.assertRaises(RuntimeError):apply(c,p)
            r.action.reset_mock();r.action.side_effect=None;c=TutorialController(r)
            for _ in range(4):apply(c,p)
            r.action.assert_not_called();self.assertEqual(r.s['tutorial']['combat_latch'],0)

    def test_changed_hp_or_unverified_body_does_not_authorize_completion(self):
        r=Mock();r.s={};r.ticket=None;r.evidence.return_value='offline';c=TutorialController(r)
        apply(c,plan());apply(c,plan());old=r.s['tutorial']['actions'][0];old['at']=time.time()-10
        changed=plan();changed['proof'][1]['text']='99/100'
        for _ in range(4):apply(c,changed)
        self.assertEqual(r.action.call_count,1);self.assertNotIn('basic_skill_selection',old)


def level_frame():
    f=frame([('1/2',212,26),('100/100',430,858)])
    f.image[481:505,1020:1048]=(25,180,70)
    f.image[475:510,975:1018]=(0,0,220)
    f.image[480:486,1049:1120]=(25,180,70)
    return f


class AllyTargetRestoreTests(unittest.TestCase):
    def current(self):
        f=frame([('伊赛丽亚',420,808),('276/1249',431,858),('2/2',212,26),('2',465,312),('3',300,456)])
        f.image[735:755,1335:1470]=(240,240,240);f.image[755:780,1335:1470]=(0,220,240)
        f.image[780:880,1230:1320]=(0,0,220);f.image[780:830,1230:1275]=(220,100,0)
        for x,y in ((465,312),(300,456)):
            f.image[y-20:y+20,x-20:x+20]=(0,0,220)
            f.image[y-10:y-4,x+25:x+120]=(30,190,90)
        return f

    def test_only_positive_iseria_second_skill_and_allied_shields_restore_first(self):
        from tutorial_core import restore_offensive_basic_plan
        f=self.current();p=restore_offensive_basic_plan(f)
        self.assertIsNotNone(p);self.assertEqual(p['target']['x'],1275)
        # One merged shield digit may use its present shield+adjacent HP shape.
        f.words.pop(-1);self.assertIsNotNone(restore_offensive_basic_plan(f))
        for invalid in ('actor','second_skill','shield','wave'):
            f=self.current()
            if invalid=='actor':f.words[0]['text']='unknown'
            elif invalid=='second_skill':f.image[735:780,1335:1470]=22
            elif invalid=='shield':f.image[150:600,250:600]=22
            else:f.words.pop(2)
            self.assertIsNone(restore_offensive_basic_plan(f),invalid)


class CurrentEnemyLevelTests(unittest.TestCase):
    def test_missing_full_ocr_level_is_rebuilt_from_current_badge_dual_read(self):
        f=level_frame();ocr=Mock(return_value=([['25',.999]],None));strengthen_enemy_levels(f,ocr)
        added=[w for w in f.words if w.get('source')=='current_enemy_level_badge_dual_read']
        self.assertEqual(len(added),1);self.assertEqual(added[0]['text'],'25');self.assertEqual(ocr.call_count,2)
        self.assertEqual(added[0]['verification_scores'],[.999,.999])

    def test_purple_level_badge_and_red_remaining_hp_still_use_current_dual_reads(self):
        f=level_frame();f.image[481:505,1020:1048]=(150,25,130);f.image[480:486,1049:1120]=(0,0,190)
        ocr=Mock(return_value=([['37',.999]],None));strengthen_enemy_levels(f,ocr)
        added=[w for w in f.words if w.get('source')=='current_enemy_level_badge_dual_read']
        self.assertEqual(len(added),1);self.assertEqual(added[0]['text'],'37')

    def test_weak_disagree_non_numeric_zero_or_existing_field_never_invent_level(self):
        for values in ([('25',.979),('25',.999)],[('25',.999),('26',.999)],[('0',.999),('0',.999)],[('100',.999),('100',.999)],[('?',.999),('?',.999)]):
            f=level_frame();ocr=Mock(side_effect=[([[t,s]],None) for t,s in values]);strengthen_enemy_levels(f,ocr)
            self.assertFalse(any(w.get('source')=='current_enemy_level_badge_dual_read' for w in f.words))
        f=level_frame();f.words.extend(frame([('19',1034,493)]).words);ocr=Mock();strengthen_enemy_levels(f,ocr);ocr.assert_not_called()

    def test_missing_shield_hp_badge_or_battle_fields_never_runs_ocr(self):
        for change in ('shield','bar','badge','wave','hp'):
            f=level_frame()
            if change=='shield':f.image[475:510,975:1018]=22
            elif change=='bar':f.image[480:486,1049:1120]=22
            elif change=='badge':f.image[481:505,1020:1048]=22
            elif change=='wave':f.words.pop(0)
            else:f.words.pop(1)
            ocr=Mock();strengthen_enemy_levels(f,ocr);ocr.assert_not_called()

class ChapterRewardLayoutTests(unittest.TestCase):
    def reward(self,tiers=(3,9,15),count=3):
        words=[('第6时代Episode',197,43),('第2章相信自己可以守护',187,138),
               (str(count)+'/'+str(tiers[-1]),67,774),('观看故事',1391,827)]
        words.extend((str(n),x,773) for n,x in zip(tiers,(205,323,448)))
        f=frame(words);runner.cv2.circle(f.image,(158,793),6,(0,100,240),-1);return f

    def test_fifteen_and_other_current_layouts_do_not_assume_nine_stars(self):
        from tutorial_core import chapter_star_reward_plan,chapter_reward_layout
        for tiers,count in (((3,9,15),3),((10,20,30),10),((2,5,8),2)):
            f=self.reward(tiers,count);p=chapter_star_reward_plan(f)
            self.assertIsNotNone(p);self.assertEqual(chapter_reward_layout(f)['tiers'],list(tiers))
            self.assertEqual(p['target']['x'],187)

    def test_missing_weak_duplicate_wrong_last_or_nonascending_thresholds_never_claim(self):
        from tutorial_core import chapter_star_reward_plan
        for invalid in ('missing','weak','duplicate','wrong_last','descending','insufficient'):
            f=self.reward()
            if invalid=='missing':f.words.pop(-2)
            elif invalid=='weak':f.words[-2]['score']=.979
            elif invalid=='duplicate':f.words.append(dict(f.words[-2]))
            elif invalid=='wrong_last':f.words[-1]['text']='14'
            elif invalid=='descending':f.words[-2]['text']='2'
            else:f.words[2]['text']='2/15'
            self.assertIsNone(chapter_star_reward_plan(f),invalid)

    def test_current_roi_dual_reads_are_required_and_original_weak_words_retained(self):
        from tutorial_ocr import strengthen_chapter_reward_thresholds
        from tutorial_core import chapter_reward_layout
        f=self.reward();original=copy.deepcopy(f.words)
        for w in f.words[-3:]:w['score']=.8
        replies=[]
        for text in ('3','9','15'):
            replies.extend([([([[0,0],[1,0],[1,1],[0,1]],text,.999)],None)]*2)
        ocr=Mock(side_effect=replies);strengthen_chapter_reward_thresholds(f,ocr)
        self.assertEqual(chapter_reward_layout(f)['tiers'],[3,9,15]);self.assertEqual(ocr.call_count,6)
        self.assertEqual([w['score'] for w in f.words[4:7]],[.8,.8,.8])
        for value in (.979,):
            f=self.reward();f.words=f.words[:4]
            ocr=Mock(return_value=([([[0,0],[1,0],[1,1],[0,1]],'3',value)],None))
            strengthen_chapter_reward_thresholds(f,ocr);self.assertIsNone(chapter_reward_layout(f))


if __name__=='__main__':unittest.main()
