"""Free Theater reward belongs to its own row, not the newly selected episode."""
import copy
from dataclasses import replace
from pathlib import Path
import tempfile,time,unittest
from PIL import Image,ImageDraw
from task_blockers import TaskAttention
from theater_core import Episode,Reading,classify,plan
from theater_directory import reward_claim_target
from theater_journal import TheaterJournal
from theater_vision import TheaterVision
from theater_worker import read_observation
import test_theater as helpers


def icon():
    im=Image.new('RGB',(1600,900),'#111111');d=ImageDraw.Draw(im)
    d.line([(1104,719),(1104,732)],fill='#999999',width=4)
    d.line([(1097,727),(1104,735),(1112,727)],fill='#999999',width=4)
    d.line([(1090,737),(1090,746),(1120,746),(1120,737)],fill='#999999',width=4)
    return im


def labels():return helpers.observation([helpers.token('领取观览奖励',950,735)])


class TheaterRewardTests(unittest.TestCase):
    def test_label_and_down_arrow_with_separate_u_tray_form_one_control(self):
        t=reward_claim_target(icon(),labels());self.assertIsNotNone(t)
        self.assertEqual(t.source,'theater_reward_claim');self.assertTrue(1080<t.center[0]<1140)
        self.assertIsNone(reward_claim_target(Image.new('RGB',(1600,900),'#111111'),labels()))
        self.assertIsNone(reward_claim_target(icon(),helpers.observation()))

    def test_weak_duplicate_label_or_wrong_position_does_not_target(self):
        for token in (helpers.token('领取观览奖励',950,735,score=.4),helpers.token('领取观览奖励',500,735)):
            self.assertIsNone(reward_claim_target(icon(),helpers.observation([token])))
        o=labels();o.tokens.append(o.tokens[0]);self.assertIsNone(reward_claim_target(icon(),o))
        im=icon();ImageDraw.Draw(im).rectangle((1080,737,1140,760),fill='#111111')
        self.assertIsNone(reward_claim_target(im,labels()))

    def test_claim_requires_reward_episode_matches_active_even_when_next_is_selected(self):
        reading=Reading('theater_reward_ready',helpers.token('claim',1100,735),Episode('没落大地',10,1),reward_episode=Episode('没落大地',9,1))
        active=dict(key=Episode('没落大地',9,1).key,run_id='run',phase='story',playback_evidence='play.png')
        self.assertEqual(plan(reading,{'active':active},'run'),'claim_reward')
        for a in (None,{**active,'key':Episode('没落大地',10,1).key},{**active,'run_id':'old'},
                  {**active,'phase':'await_ticket'},dict(key=active['key'],run_id='run',phase='story')):
            with self.assertRaises(TaskAttention):plan(reading,{'active':a},'run')

    def test_claim_only_once_not_completion_and_external_intent_blocks_repeat(self):
        with tempfile.TemporaryDirectory() as folder:
            j=TheaterJournal(folder,'run');r=classify(helpers.listing())
            rec=j.reserve('open',r,'before.png');j.finish(rec,'sent')
            j.state['active'].update(phase='story',playback_evidence='play.png');j.save()
            before=copy.deepcopy(j.state)
            claim=Reading('theater_reward_ready',helpers.token('claim',1100,735),r.episode,reward_episode=r.episode)
            self.assertFalse(j.observe(claim,'ready.png'))
            rec=j.reserve('claim_reward',claim,'ready.png');j.finish(rec,'sent')
            with self.assertRaises(TaskAttention):j.reserve('claim_reward',claim,'same.png')
            for key in ('completed','attempted','entry_dispatches','last_cleared','active'):self.assertEqual(j.state[key],before[key])
            path=j.reward_operator_dispatch_path();path.parent.mkdir();path.write_text('{}',encoding='utf-8')
            with self.assertRaises(TaskAttention):j.reserve('claim_reward',claim,'same.png')

    def test_private_native_reward_ready_replay(self):
        path=Path(__file__).resolve().parents[1]/'.local/theater-reward-20261104/ready.png'
        if not path.is_file():self.skipTest('未分发真实剧场私有画面')
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        with Image.open(path) as im:o=TheaterVision().apply(im,read_observation(im,ocr,time.monotonic()))
        r=classify(o);self.assertEqual(r.scene,'theater_reward_ready')
        self.assertEqual(r.episode,Episode('没落大地',10,1));self.assertEqual(r.reward_episode,Episode('没落大地',9,1))
        self.assertNotIn(9,r.completed)
        o.tokens.append(helpers.token('确认',800,500))
        self.assertEqual(classify(o).scene,'theater_unknown_dialog')

    def test_free_reward_notice_requires_all_captions_unique_close_not_entry_chain(self):
        words=[helpers.token('获得奖励',800,210),helpers.token('已领取奖励。',800,290),
               helpers.token('若有未领取的观览奖励，则将汇总后统一领取。',800,315),helpers.token('点击关闭',800,660)]
        r=classify(helpers.observation(words));self.assertEqual(r.scene,'theater_reward_notice')
        active=dict(run_id='run',phase='story',playback_evidence='play.png')
        self.assertEqual(plan(r,{'active':active},'run'),'close_reward_notice')
        self.assertEqual(plan(r,{'active':None},'run'),'close_reward_notice')
        for i in range(len(words)):
            o=helpers.observation(words[:i]+words[i+1:])
            self.assertNotEqual(classify(o).scene,'theater_reward_notice')
        for extra in ([helpers.token('确认',800,500)],[helpers.token('点击关闭',900,660)],
                      [helpers.token('购买门票',800,500,score=.3)]):
            self.assertNotEqual(classify(helpers.observation(words+extra)).scene,'theater_reward_notice')

class RewardArrowResamplingTests(unittest.TestCase):
    def shifted_tray(self,shift):
        im=Image.new('RGB',(1600,900),'#111111');d=ImageDraw.Draw(im)
        d.line([(1104,719),(1104,732)],fill='#999999',width=4)
        d.line([(1097,727),(1104,735),(1112,727)],fill='#999999',width=4)
        d.line([(1090,737+shift),(1090,746+shift),(1120,746+shift),(1120,737+shift)],fill='#999999',width=4)
        return im

    def test_separate_arrow_tray_allow_only_two_px_bbox_overlap(self):
        self.assertIsNotNone(reward_claim_target(self.shifted_tray(-1),labels()))
        self.assertIsNotNone(reward_claim_target(self.shifted_tray(-2),labels()))

    def test_deeply_overlapping_or_merged_shapes_and_missing_label_still_reject(self):
        self.assertIsNone(reward_claim_target(self.shifted_tray(-6),labels()))
        image=self.shifted_tray(-2);ImageDraw.Draw(image).line([(1104,730),(1104,746)],fill='#999999',width=4)
        self.assertIsNone(reward_claim_target(image,labels()))
        self.assertIsNone(reward_claim_target(self.shifted_tray(-2),helpers.observation()))


    def test_private_resampled_reward_preserves_episode_ownership(self):
        path = (Path(__file__).resolve().parents[1] / '.local' /
                'theater-repair-20261105' / '20261105T115920.png')
        if not path.is_file():
            self.skipTest('未分发本次原生缩放奖励私有画面')
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
        with Image.open(path) as image:
            obs = TheaterVision().apply(image, read_observation(image, ocr, time.monotonic()))
        reading = classify(obs)
        self.assertEqual(reading.scene, 'theater_reward_ready')
        self.assertEqual(reading.episode, Episode('没落大地', 2, 2))
        self.assertEqual(reading.reward_episode, Episode('没落大地', 1, 2))
        self.assertNotIn(1, reading.completed)
        active = dict(key=reading.reward_episode.key, run_id='run', phase='story',
                      playback_evidence='play.png')
        self.assertEqual(plan(reading, {'active': active}, 'run'), 'claim_reward')
        with self.assertRaises(TaskAttention):
            plan(reading, {'active': {**active, 'key': reading.episode.key}}, 'run')
        # A newly selected paid episode cannot substitute for the clipped
        # reward-owning row, and an unknown modal still forbids all input.
        clipped = copy.deepcopy(obs)
        clipped.tokens = [t for t in clipped.tokens if t.text != '第1集']
        self.assertNotEqual(classify(clipped).scene, 'theater_reward_ready')
        obs.tokens.append(helpers.token('确认', 800, 500))
        self.assertEqual(classify(obs).scene, 'theater_unknown_dialog')


class RewardReturnObservationTests(unittest.TestCase):
    def state(self):
        key=Episode('没落大地',2,2).key
        return dict(active=dict(key=key,series='没落大地',number=2,season=2,
                                run_id='run',phase='story',playback_evidence='play.png'),
                    actions=[dict(kind='claim_reward',key=key,run_id='run',status='sent',
                                  episode=Episode('没落大地',3,2).key)])

    def pending(self,reading,state=None):
        from theater_worker import reward_return_pending
        return reward_return_pending(reading,self.state() if state is None else state,'run')

    def test_only_same_sent_claim_list_transition_is_zero_input_observation(self):
        r=Reading('theater_list',episode=Episode('没落大地',3,2))
        self.assertTrue(self.pending(r));self.assertTrue(self.pending(Reading('theater_list')))
        s=self.state();s['actions'].append(dict(kind='close_reward_notice',key=s['active']['key'],run_id='run',status='sent'))
        self.assertTrue(self.pending(r,s))
        self.assertFalse(self.pending(Reading('theater_list',episode=r.episode,completed=(2,))))

    def test_known_notice_and_higher_priority_pages_never_wait(self):
        for scene in ('theater_reward_notice','theater_reward_ready','theater_defeat',
                      'theater_blocked','theater_unknown_dialog','theater_story','theater_battle'):
            self.assertFalse(self.pending(Reading(scene)))

    def test_unknown_duplicate_foreign_claim_or_wrong_episode_cannot_borrow_wait(self):
        r=Reading('theater_list',episode=Episode('没落大地',3,2))
        for change in ('missing','unknown','reserved','not_sent','duplicate','foreign','no_play','phase','source','close_unknown'):
            with self.subTest(change=change):
                s=self.state()
                if change=='missing':s['actions']=[]
                elif change in ('unknown','reserved','not_sent'):s['actions'][0]['status']=change
                elif change=='duplicate':s['actions']*=2
                elif change=='foreign':s['actions'][0]['run_id']='other'
                elif change=='no_play':del s['active']['playback_evidence']
                elif change=='phase':s['active']['phase']='await_ticket'
                elif change=='source':s['actions'][0]['episode']=Episode('没落大地',8,2).key
                else:s['actions'].append(dict(kind='close_reward_notice',key=s['active']['key'],run_id='run',status='unknown'))
                self.assertFalse(self.pending(r,s))
        for ep in (Episode('没落大地',4,2),Episode('没落大地',3,1),Episode('其他剧目',3,2)):
            self.assertFalse(self.pending(Reading('theater_list',episode=ep)))

    def test_worker_waits_through_post_claim_list_then_closes_and_requires_independent_completion(self):
        from unittest.mock import patch
        ep=Episode('没落大地',2,2);nxt=Episode('没落大地',3,2)
        target=helpers.token('control',1000,600)
        readings=[Reading('theater_list',target,ep,ticket_cost=1,ticket_stock=12),
                  Reading('theater_ticket',target,ticket_cost=1,ticket_stock=12),
                  Reading('theater_guide',target),Reading('theater_story',target),
                  Reading('theater_reward_ready',target,nxt,reward_episode=ep),
                  Reading('theater_list',target,nxt,ticket_cost=1,ticket_stock=11),
                  Reading('theater_reward_notice',helpers.token('点击关闭',800,660)),
                  Reading('theater_list',target,nxt,completed=(2,),ticket_cost=1,ticket_stock=11)]
        with patch('theater_worker.classify',side_effect=readings):
            transport,ctl,state=helpers.TheaterWorkerTests().run_frames([helpers.observation() for _ in readings])
        kinds=[a['kind'] for a in state['actions']]
        self.assertEqual(kinds.count('claim_reward'),1)
        self.assertEqual(kinds.count('close_reward_notice'),1)
        self.assertEqual(kinds.count('ticket'),1)
        self.assertIn(ep.key,state['completed'])
        ctl.attention.assert_not_called()
        self.assertTrue(any('领奖已发送' in str(c) for c in ctl.status.call_args_list))


class StandaloneRewardNoticeTests(unittest.TestCase):
    def notice(self):
        return helpers.observation([
            helpers.token('获得奖励',800,210), helpers.token('已领取奖励。',800,290),
            helpers.token('若有未领取的观览奖励，则将汇总后统一领取。',800,315),
            helpers.token('点击关闭',800,660)])

    def test_known_free_notice_needs_no_active_and_is_not_an_entry_or_completion(self):
        r=classify(self.notice())
        for active in (None,dict(run_id='old',phase='await_ticket'),
                       dict(run_id='run',phase='story')):
            self.assertEqual(plan(r,{'active':active},'run'),'close_reward_notice')
        for target in (None,helpers.token('确认',800,660),helpers.token('点击关闭',800,660,score=.3)):
            with self.assertRaises(TaskAttention):plan(Reading('theater_reward_notice',target),{'active':None},'run')

    def test_dismissal_preserves_archived_playback_all_history_and_single_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            old=TheaterJournal(folder,'old')
            r=classify(helpers.listing())
            rec=old.reserve('open',r,'open.png');old.finish(rec,'sent')
            old.state['active'].update(phase='story',playback_evidence='play.png');old.save()
            current=TheaterJournal(folder,'run');before=copy.deepcopy(current.state)
            notice=classify(self.notice())
            self.assertFalse(current.observe(notice,'notice.png'))
            rec=current.reserve(plan(notice,current.state,'run'),notice,'notice.png')
            current.finish(rec,'sent')
            self.assertIsNone(current.state['active'])
            for k in ('attempted','completed','entry_dispatches','unresolved_entries','last_cleared'):
                self.assertEqual(current.state[k],before[k],k)
            self.assertEqual(current.state['actions'][:-1],before['actions'])
            self.assertEqual(current.state['actions'][-1]['kind'],'close_reward_notice')
            self.assertIsNone(current.state['actions'][-1]['key'])
            with self.assertRaises(TaskAttention):current.reserve('close_reward_notice',notice,'again.png')

    def test_worker_from_known_notice_closes_once_then_checks_next_new_episode(self):
        from test_theater_directory import directory
        im,obs=directory(stock=11)
        next_frame=TheaterVision().apply(im,obs)
        transport,ctl,state=helpers.TheaterWorkerTests().run_frames([self.notice(),next_frame])
        self.assertEqual([a['kind'] for a in state['actions']],['close_reward_notice','open'])
        self.assertEqual(len(state['attempted']),1)
        self.assertEqual(state['completed'],{})
        ctl.attention.assert_not_called()

    def test_incomplete_weak_misplaced_or_risky_notice_never_authorizes_close(self):
        for i in range(4):
            for change in ('remove','weak','position'):
                obs=self.notice()
                if change=='remove':obs.tokens.pop(i)
                elif change=='weak':obs.tokens[i]=replace(obs.tokens[i],score=.3)
                else:obs.tokens[i]=replace(obs.tokens[i],x=10,y=10)
                self.assertNotEqual(classify(obs).scene,'theater_reward_notice')
        for text in ('购买门票','英雄持有数量已达上限','连接失败','战斗失败','确认','取消'):
            obs=self.notice();obs.tokens.append(helpers.token(text,800,500,score=.3))
            self.assertNotEqual(classify(obs).scene,'theater_reward_notice')

    def test_private_actual_notice_from_new_run_has_valid_close_without_backfill(self):
        path=Path(__file__).resolve().parents[1]/'.local/theater-stall-20261105/20261105T135154.png'
        if not path.is_file():self.skipTest('未分发新开始后的奖励提示私有画面')
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        with Image.open(path) as im:
            obs=TheaterVision().apply(im,read_observation(im,ocr,time.monotonic()))
        r=classify(obs)
        self.assertEqual(r.scene,'theater_reward_notice')
        self.assertEqual(plan(r,{'active':None},'run'),'close_reward_notice')
        self.assertEqual(r.completed,())
