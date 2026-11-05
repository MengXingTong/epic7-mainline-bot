"""A sent ticket may expose a FREE play button before guide/story; never re-pay."""
import copy,json,hashlib,tempfile,time,unittest
from pathlib import Path
from PIL import Image,ImageDraw
from task_blockers import TaskAttention
from theater_core import Episode,Reading,classify,plan
from theater_directory import paid_play_reading
from theater_vision import TheaterVision
from theater_worker import read_observation
from theater_journal import TheaterJournal
import test_theater as helpers


class PaidPlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'evidence').mkdir()
        self.image=Image.new('RGB',(1600,900),'#222222');ImageDraw.Draw(self.image).rectangle((800,795,1150,880),fill='#167b30')
        self.obs=helpers.observation([helpers.token('月光剧场',150,40),helpers.token('目录',1290,140),
            helpers.token('没落',140,180,h=100),helpers.token('大地',300,250,h=130),
            helpers.token('第9集·独立字幕I',300,620),helpers.token('第8集',1300,300),
            helpers.token('第9集',1300,440),helpers.token('可观览',1300,475),
            helpers.token('第10集',1300,580),helpers.token('无法观览',1300,615),helpers.token('进行观览',1000,835)],
            visuals=['theater_soft_selected:9'])
        ep=Episode('没落大地',9,1)
        self.state={'active':dict(key=ep.key,series=ep.series,number=9,season=1,phase='await_guide',run_id='run',evidence='evidence/open.png'),
                    'actions':[dict(key=ep.key,kind='ticket',status='sent',run_id='run')]}
        path=self.root/'evidence/open.png';self.image.save(path)
        meta=dict(scene='theater_list',run_id='run',episode=vars(ep),width=1600,height=900,
                  image_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),tokens=[vars(t) for t in self.obs.tokens])
        path.with_suffix('.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
        self.reading=classify(self.obs)
    def read(self):return paid_play_reading(self.image,self.obs,self.reading,self.state,'run',self.root)

    def test_exact_current_chain_and_immutable_subtitle_recognize_only_free_play(self):
        r=self.read();self.assertEqual(r.scene,'theater_paid_ready');self.assertEqual(r.episode,Episode('没落大地',9,1))
        self.assertEqual(plan(r,self.state,'run'),'play');self.assertIsNone(r.ticket_cost)
    def test_missing_unknown_duplicate_or_old_ticket_does_not_authorize(self):
        original=copy.deepcopy(self.state)
        for mode in ('missing','reserved','duplicate','old'):
            self.state=copy.deepcopy(original)
            if mode=='missing':self.state['actions']=[]
            elif mode=='reserved':self.state['actions'][0]['status']='reserved'
            elif mode=='duplicate':self.state['actions']*=2
            else:self.state['actions'][0]['run_id']='old'
            self.assertNotEqual(self.read().scene,'theater_paid_ready')
    def test_bad_source_hash_or_run_or_subtitle_blocks_context(self):
        p=self.root/'evidence/open.json';original=json.loads(p.read_text(encoding='utf-8'))
        for key,value in [('image_sha256','bad'),('run_id','old'),('episode',vars(Episode('没落大地',9,2)))]:
            meta={**original,key:value};p.write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')
            self.assertNotEqual(self.read().scene,'theater_paid_ready')
        p.write_text(json.dumps(original,ensure_ascii=False),encoding='utf-8')
        from dataclasses import replace
        self.obs.tokens[4]=replace(self.obs.tokens[4],text='第9集·不同的字幕')
        self.assertNotEqual(self.read().scene,'theater_paid_ready')
    def test_not_green_missing_available_or_unpaid_cost_never_becomes_free(self):
        original=copy.deepcopy(self.obs)
        self.image=Image.new('RGB',(1600,900),'#222222');self.assertNotEqual(self.read().scene,'theater_paid_ready')
        self.image=Image.open(self.root/'evidence/open.png').copy()
        self.obs.tokens.pop(7);self.assertNotEqual(self.read().scene,'theater_paid_ready')
        self.obs=copy.deepcopy(original);self.obs.tokens.append(helpers.token('1/9',890,835))
        self.assertNotEqual(self.read().scene,'theater_paid_ready')
    def test_modal_or_wrong_active_phase_and_episode_stay_blocked(self):
        from dataclasses import replace
        for scene in ('theater_unknown_dialog','theater_blocked','theater_defeat'):
            r=paid_play_reading(self.image,self.obs,replace(self.reading,scene=scene),self.state,'run',self.root)
            self.assertEqual(r.scene,scene)
        self.state['active']['phase']='story';self.assertNotEqual(self.read().scene,'theater_paid_ready')
    def test_play_and_ticket_never_repeat_and_play_does_not_count_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            j=TheaterJournal(folder,'run');r=classify(helpers.listing())
            a=j.reserve('open',r,'open.png');j.finish(a,'sent');a=j.reserve('ticket',r,'ticket.png');j.finish(a,'sent')
            before=copy.deepcopy(j.state)
            paid=Reading('theater_paid_ready',r.target,r.episode)
            a=j.reserve('play',paid,'free.png');j.finish(a,'sent')
            with self.assertRaises(TaskAttention):j.reserve('play',paid,'same.png')
            for key in ('attempted','entry_dispatches','completed','last_cleared','active'):self.assertEqual(j.state[key],before[key])
    def test_independent_completed_row_survives_next_locked_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            j=TheaterJournal(folder,'run');r=classify(helpers.listing(9));a=j.reserve('open',r,'open.png');j.finish(a,'sent')
            j.state['active'].update(phase='story',playback_evidence='play.png');j.save()
            reading=Reading('theater_blocked',episode=Episode(r.episode.series,11),completed=(9,),reason='next row locked')
            self.assertTrue(j.observe(reading,'independent.png'));self.assertEqual(len(j.state['completed']),1)
    def test_private_paid_native_page_readonly_replay(self):
        root=Path(__file__).resolve().parents[1]/'.local/theater-paid-20261104'
        if not (root/'paid.png').exists():self.skipTest('未分发真实剧场私有画面')
        meta=json.loads((root/'evidence/open.json').read_text(encoding='utf-8'))
        state=copy.deepcopy(self.state);state['active']['source_run_id']=meta['run_id']
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        with Image.open(root/'paid.png') as image:
            obs=TheaterVision().apply(image,read_observation(image,ocr,time.monotonic()))
            r=paid_play_reading(image,obs,classify(obs),state,'run',root)
        self.assertEqual(r.scene,'theater_paid_ready');self.assertEqual(r.episode,Episode('没落大地',9,1))

    def test_known_cost_unknown_page_can_be_recognized_only_after_sent_ticket(self):
        from dataclasses import replace
        self.reading=replace(self.reading,scene='theater_blocked',reason='未核实本帧1张门票/持有数量，或门票不足；不购买。')
        self.assertEqual(self.read().scene,'theater_paid_ready')
        self.state['actions']=[]
        self.assertNotEqual(self.read().scene,'theater_paid_ready')

    def test_partial_paid_return_observes_then_guide_on_first_complete_frame(self):
        partial=helpers.observation([helpers.token('月光剧场',180,70),helpers.token('进行观览',1400,805)])
        transport,ctl,state=helpers.TheaterWorkerTests().run_frames([
            helpers.listing(),helpers.ticket(),partial,partial,helpers.guide(),helpers.observation(visuals=['theater_story'])],processing_seconds=.001)
        self.assertEqual(transport.tap.call_count,4);ctl.attention.assert_not_called()
        self.assertTrue(any(c.kwargs.get('mode')=='waiting_scene' for c in ctl.status.call_args_list))
        self.assertEqual(len([a for a in state['actions'] if a['kind']=='ticket']),1)

    def test_resource_overlay_during_paid_return_does_not_wait_or_send(self):
        blocked=helpers.observation([helpers.token('购买门票',800,500)])
        transport,ctl,state=helpers.TheaterWorkerTests().run_frames([helpers.listing(),helpers.ticket(),blocked],processing_seconds=.001)
        self.assertEqual(transport.tap.call_count,2);ctl.attention.assert_called_once()
        self.assertEqual(ctl.attention.call_args.args[0].code,'theater_blocked')


class PaidReturnWaitTests(unittest.TestCase):
    """A recognized current row may still show stale cost after ticket sending."""
    def setUp(self):
        from theater_worker import paid_return_pending
        self.pending = paid_return_pending
        self.ep = Episode('没落大地', 14, 1)
        self.reading = Reading('theater_list', episode=self.ep, ticket_cost=1, ticket_stock=6)
        self.state = {'active':dict(key=self.ep.key, series=self.ep.series, number=14,
                      season=1, phase='await_guide', run_id='run'),
                      'actions':[dict(key=self.ep.key, kind='ticket', status='sent', run_id='run')]}

    def test_exact_current_row_with_stale_fee_waits_without_authorizing_payment(self):
        before = copy.deepcopy(self.state)
        self.assertTrue(self.pending(self.reading, self.state, 'run'))
        self.assertEqual(self.state, before)
        with self.assertRaises(TaskAttention):
            plan(self.reading, self.state, 'run')

    def test_other_episode_season_series_or_completed_row_never_borrows_wait(self):
        from dataclasses import replace
        for episode in (Episode(self.ep.series, 13, 1), Episode(self.ep.series, 14, 2),
                        Episode('其他剧目', 14, 1)):
            with self.subTest(episode=episode):
                self.assertFalse(self.pending(replace(self.reading, episode=episode), self.state, 'run'))
        self.assertFalse(self.pending(replace(self.reading, completed=(14,)), self.state, 'run'))

    def test_only_one_sent_current_run_ticket_can_receive_zero_input_wait(self):
        original = copy.deepcopy(self.state)
        for mode in ('missing', 'reserved', 'unknown', 'not_sent', 'duplicate', 'old_ticket', 'old_active'):
            state = copy.deepcopy(original)
            if mode == 'missing': state['actions'] = []
            elif mode == 'duplicate': state['actions'] *= 2
            elif mode == 'old_ticket': state['actions'][0]['run_id'] = 'old'
            elif mode == 'old_active': state['active']['run_id'] = 'old'
            else: state['actions'][0]['status'] = mode
            with self.subTest(mode=mode):
                self.assertFalse(self.pending(self.reading, state, 'run'))

    def test_complete_controls_blockers_and_known_transition_use_normal_priority(self):
        from dataclasses import replace
        for scene in ('theater_paid_ready', 'theater_guide', 'theater_story', 'theater_blocked',
                      'theater_defeat', 'theater_unknown_dialog', 'theater_unknown', 'theater_transition'):
            with self.subTest(scene=scene):
                self.assertFalse(self.pending(replace(self.reading, scene=scene), self.state, 'run'))
        self.state['active']['playback_evidence'] = 'already-playing.png'
        self.assertFalse(self.pending(self.reading, self.state, 'run'))

    def test_prior_play_or_guide_intent_keeps_transition_and_dedup_guards(self):
        for kind in ('play', 'guide'):
            for status in ('reserved', 'sent', 'unknown', 'not_sent'):
                state = copy.deepcopy(self.state)
                state['actions'].append(dict(key=self.ep.key, kind=kind, status=status, run_id='run'))
                self.assertFalse(self.pending(self.reading, state, 'run'))

    def test_worker_observes_readable_paid_return_then_uses_complete_guide_immediately(self):
        transport, ctl, state = helpers.TheaterWorkerTests().run_frames([
            helpers.listing(), helpers.ticket(), helpers.listing(), helpers.listing(),
            helpers.guide(), helpers.observation(visuals=['theater_story'])], processing_seconds=.001)
        self.assertEqual(transport.tap.call_count, 4)
        ctl.attention.assert_not_called()
        self.assertEqual(len([x for x in state['actions'] if x['kind'] == 'ticket']), 1)
        self.assertEqual(len([c for c in ctl.status.call_args_list if c.kwargs.get('mode') == 'waiting_scene']), 2)

    def test_worker_different_row_immediately_preserves_original_paid_chain(self):
        transport, ctl, state = helpers.TheaterWorkerTests().run_frames([
            helpers.listing(14), helpers.ticket(), helpers.listing(15)], processing_seconds=.001)
        self.assertEqual(transport.tap.call_count, 2)
        ctl.attention.assert_called_once()
        self.assertEqual(state['active']['number'], 14)
        self.assertEqual(state['active']['phase'], 'await_guide')
        self.assertEqual(state['completed'], {})

    def test_stale_paid_return_expires_without_payment_play_or_completion(self):
        from unittest.mock import patch
        from assistant_worker import capture_fresh as original_capture
        # Each mocked capture gets its real simulated capture time; old snapshots
        # must not accidentally expire and mask the fifteen-second wait limit.
        def fresh(*args, **kwargs):
            snap = original_capture(*args, **kwargs)
            snap.captured_at = time.monotonic()
            return snap
        with patch('assistant_worker.capture_fresh', side_effect=fresh):
            transport, ctl, state = helpers.TheaterWorkerTests().run_frames([
                helpers.listing(), helpers.ticket(), *[helpers.listing() for _ in range(50)]],
                processing_seconds=.4)
        self.assertEqual(transport.tap.call_count, 2)
        ctl.attention.assert_called_once()
        self.assertEqual(ctl.attention.call_args.args[0].code, 'theater_unresolved')
        self.assertEqual(state['active']['phase'], 'await_guide')
        self.assertEqual(state['completed'], {})
        self.assertEqual(len([x for x in state['actions'] if x['kind'] == 'ticket']), 1)
        self.assertFalse(any(x['kind'] == 'play' for x in state['actions']))
