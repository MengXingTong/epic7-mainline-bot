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
