"""Proven free-UI interception is not gameplay replay; no native input."""
import copy,datetime,time,unittest
from test_story_only_nodes import frame,fake_runner
from entry_journal import reserve_entry,finish_dispatch
from free_story_handoff import source_handoff,dispatch_handoff
import runner


def case():
    before=frame(stage=6);after=frame(stage=6)
    for f in (before,after):
        f.words[0]['text']='第6时代Episode';f.words[1]['text']='第1章使徒现身'
    runner.cv2.circle(before.image,(407,793),6,(0,100,240),-1)
    runner.cv2.polylines(after.image,[runner.np.array([(418,824),(429,836),(450,811)],runner.np.int32)],False,(0,220,80),6)
    r=fake_runner(after);d=r.map_ticket(after)[0];a=dict(d,cost=0,entry_kind='story_only',start_epoch=time.time())
    record=reserve_entry(r.s,d['key'],a);finish_dispatch(record,'sent');r.s['active']=a
    now=datetime.datetime.now(runner.TZ);t=now.isoformat(timespec='seconds');later=(now+datetime.timedelta(seconds=1)).isoformat(timespec='seconds')
    events=[dict(kind='action',action='观看故事（仅一次）',stage=d['key'],time=t),dict(kind='screen',screen='story_reward',stage=d['key'],time=later),dict(kind='action',action='关闭已发放的免费奖励遮罩',stage=d['key'],time=later),dict(kind='screen',screen='map',stage=d['key'],time=later)]
    return r,before,after,events,d,runner.mainline_map_control(after)

class FreeStoryHandoffTests(unittest.TestCase):
    def test_proven_interception_keeps_attempt_and_original_sent_then_continues_once(self):
        r,b,f,events,d,c=case();source=source_handoff(r.s,b,f,events,d,c);self.assertIsNotNone(source)
        old=copy.deepcopy(r.s);snap=[];r.action.side_effect=lambda *args:snap.append(copy.deepcopy(r.s))
        dispatch_handoff(r,source)
        self.assertEqual(snap[0]['free_story_handoffs'][0]['status'],'reserved')
        self.assertEqual(r.s['attempted'],old['attempted']);self.assertEqual(r.s['entry_dispatches'],old['entry_dispatches'])
        self.assertEqual(r.s['free_story_handoffs'][0]['status'],'sent')
        with self.assertRaises(ValueError):dispatch_handoff(r,source)
        r.action.assert_called_once()
    def regular_episode_case(self):
        r,b,f,events,_,_=case()
        for image in (b.image,f.image):image[780:860,145:470]=22
        runner.cv2.circle(b.image,(282,793),6,(0,100,240),-1)
        runner.cv2.polylines(f.image,[runner.np.array([(293,824),(304,836),(325,811)],runner.np.int32)],False,(0,220,80),6)
        frames=[]
        for old in (b,f):
            rows=[[w['box'],('Episode 5' if i==0 else w['text']),w['score']] for i,w in enumerate(old.words)]
            for text,x,y in [('12/18',67,774),('6',205,773),('12',323,773),('18',447,773)]:
                rows.append(([[x-15,y-10],[x+15,y-10],[x+15,y+10],[x-15,y+10]],text,.999))
            frames.append(runner.Frame(old.image,rows))
        b,f=frames;r=fake_runner(f);d=r.map_ticket(f)[0];a=dict(d,cost=0,entry_kind='story_only',start_epoch=time.time())
        dispatch=reserve_entry(r.s,d['key'],a);finish_dispatch(dispatch,'sent');r.s['active']=a
        for event in events:event['stage']=d['key']
        return r,b,f,events,d,runner.mainline_map_control(f)
    def test_regular_episode_uses_current_6_12_18_layout_and_claim_check_not_stage_stars(self):
        from tutorial_core import chapter_reward_pending,chapter_star_reward_plan
        r,b,f,events,d,c=self.regular_episode_case()
        pending=chapter_reward_pending(b);self.assertEqual(pending['needed'],12)
        self.assertEqual(chapter_star_reward_plan(b)['rule'],'chapter_star_reward')
        self.assertIsNone(chapter_reward_pending(f));self.assertIsNone(chapter_star_reward_plan(f))
        source=source_handoff(r.s,b,f,events,d,c);self.assertIsNotNone(source)
        self.assertEqual(source['chapter_reward'],12);self.assertGreaterEqual(source['claimed_check_score'],.5)
        self.assertEqual(r.s['completed'],{});r.action.assert_not_called()
    def test_reward_layout_does_not_require_episode_or_chapter_title_format(self):
        from tutorial_core import chapter_star_reward_plan
        for title in ('外传 圣女追悼文','限时活动：未知的新篇章','Episode 42','第9时代Episode','', '特殊故事'):
            with self.subTest(title=title):
                r,b,f,events,d,c=self.regular_episode_case()
                for i,w in enumerate(b.words[:2]):w['text']=title if i==0 else '任意章节副标题'
                plan=chapter_star_reward_plan(b)
                self.assertIsNotNone(plan);self.assertEqual(plan['rule'],'chapter_star_reward')
                self.assertEqual(plan['target']['x'],311);self.assertEqual(r.s['completed'],{})
    def test_title_independent_reward_requires_full_layout_and_no_modal_controls(self):
        from tutorial_core import chapter_star_reward_plan
        for mode in ('weak_counter','weak_tier','missing_tier','nonascending','confirm','cancel','unknown_close','no_dot'):
            with self.subTest(mode=mode):
                r,b,f,events,d,c=self.regular_episode_case();b.words=b.words[2:]
                if mode=='weak_counter':next(w for w in b.words if w['text']=='12/18')['score']=.979
                elif mode=='weak_tier':next(w for w in b.words if w['text']=='12')['score']=.979
                elif mode=='missing_tier':b.words=[w for w in b.words if w['text']!='18']
                elif mode=='nonascending':next(w for w in b.words if w['text']=='6')['text']='13'
                elif mode=='no_dot':b.image[782:804,270:295]=22
                else:b.words.append(dict(text={'confirm':'确认','cancel':'取消','unknown_close':'点击关闭'}[mode],x=800,y=450,score=.999))
                self.assertIsNone(chapter_star_reward_plan(b))

    def test_passive_notice_observation_without_any_click_is_not_gameplay_acceptance(self):
        r,b,f,events,d,c=self.regular_episode_case()
        events.insert(-1,dict(kind='screen',screen='tutorial_completed_notice',stage=d['key']))
        events.insert(-1,dict(kind='screen',screen='unknown',stage=d['key']))
        self.assertIsNotNone(source_handoff(r.s,b,f,events,d,c))
        events.insert(-1,dict(kind='action',action='关闭已核实的免费提示（不代表关卡通关）',stage=d['key']))
        self.assertIsNone(source_handoff(r.s,b,f,events,d,c));r.action.assert_not_called()
    def test_regular_episode_still_rejects_archives_unclaimed_reward_and_actual_playback(self):
        for mode in ('archive','unclaimed','story','battle','defeat','paid','second_action'):
            with self.subTest(mode=mode):
                r,b,f,events,d,c=self.regular_episode_case()
                if mode=='archive':r.s['unresolved_entries']=[dict(entry=copy.deepcopy(r.s['active']))]
                elif mode=='unclaimed':f.image[798:855,280:350]=22
                elif mode=='paid':r.s['active']['cost']=8
                elif mode=='second_action':events.append(dict(kind='action',action='unknown'))
                else:events.insert(-1,dict(kind='screen',screen=mode))
                self.assertIsNone(source_handoff(r.s,b,f,events,d,c));r.action.assert_not_called()

    def test_absence_of_playback_is_not_itself_permission(self):
        for change in ('no_notification','no_claim_check','playback','battle','other_action','archive','wrong_current'):
            r,b,f,events,d,c=case()
            if change=='no_notification':b.image[782:804,390:420]=22
            if change=='no_claim_check':f.image[798:855,405:467]=22
            if change=='playback':r.s['active']['playback_observed_at']='observed'
            if change=='battle':events.insert(1,dict(kind='screen',screen='battle'))
            if change=='other_action':events.append(dict(kind='action',action='unverified'))
            if change=='archive':r.s['unresolved_entries']=[dict(entry=copy.deepcopy(r.s['active']))]
            if change=='wrong_current':d['key']='different'
            self.assertIsNone(source_handoff(r.s,b,f,events,d,c),change);r.action.assert_not_called()
    def test_send_failure_stays_reserved_and_original_entry_is_not_relabelled(self):
        r,b,f,events,d,c=case();source=source_handoff(r.s,b,f,events,d,c);r.action.side_effect=RuntimeError('unknown send')
        with self.assertRaises(RuntimeError):dispatch_handoff(r,source)
        self.assertEqual(r.s['free_story_handoffs'][0]['status'],'reserved')
        self.assertEqual(r.s['entry_dispatches'][d['key']][0]['status'],'sent')
        self.assertIsNone(source_handoff(r.s,b,f,events,d,c));r.action.assert_called_once()
    def test_duplicate_readonly_map_observation_does_not_erase_source_chain(self):
        r,b,f,events,d,c=case();events.append(dict(kind='screen',screen='map'))
        self.assertIsNotNone(source_handoff(r.s,b,f,events,d,c))

if __name__=='__main__':unittest.main()
