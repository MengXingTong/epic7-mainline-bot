"""Post-reward identity is anchored to immutable proof, not a guessed glow."""
import copy,hashlib,json,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from PIL import Image
from abyss_core import Token
from theater_core import Episode,classify,plan
from theater_directory import reward_return_reading
from theater_vision import TheaterVision
from theater_worker import read_observation
from test_theater_directory import directory
import test_theater as h


class RewardDirectoryContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'evidence').mkdir()
        self.old=Episode('没落大地',7,1);self.following=Episode('没落大地',8,1)
        source_image,source=directory(completed=(5,6))
        source.tokens=[replace(t,text='可获得奖励') if t.text=='6天后可观览' and 470<t.center[1]<490 else t for t in source.tokens]
        source=TheaterVision().apply(source_image,source)
        source.tokens.append(Token('verified_reward_claim',1100,735,2,2,source='theater_reward_claim',score=1.0))
        sr=classify(source);self.assertEqual(sr.scene,'theater_reward_ready')
        self.assertEqual(sr.reward_episode,self.old)
        path=self.root/'evidence/source.png';source_image.save(path)
        meta=dict(run_id='run',scene=sr.scene,episode=vars(sr.episode),width=1600,height=900,
                  captured_at=100,image_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  tokens=[vars(t) for t in source.tokens],visuals=sorted(source.visuals))
        self.meta=path.with_suffix('.json');self.meta.write_text(json.dumps(meta),encoding='utf-8')
        self.im,self.obs=directory()
        self.obs=TheaterVision().apply(self.im,self.obs)
        self.obs.visuals.discard('theater_season:1')
        self.state=dict(active=dict(key=self.old.key,series=self.old.series,number=7,season=1,
                                   run_id='run',phase='story',playback_evidence='play.png'),
                        actions=[dict(id='claim',kind='claim_reward',status='sent',run_id='run',
                                      key=self.old.key,episode=self.following.key,evidence='evidence/source.png'),
                                 dict(kind='close_reward_notice',status='sent',run_id='run',key=self.old.key,episode=None)],
                        attempted={},completed={},unresolved_entries=[])

    def resolve(self,obs=None,state=None):
        obs=copy.deepcopy(self.obs if obs is None else obs)
        return reward_return_reading(obs,classify(obs),self.state if state is None else state,'run',self.root),obs

    def standalone(self):
        state=copy.deepcopy(self.state);entry=state.pop('active');entry['run_id']='old'
        state['active']=None;state['unresolved_entries']=[dict(entry=entry)]
        state['actions'][0]['run_id']='old';state['actions'][1]['key']=None
        meta=json.loads(self.meta.read_text(encoding='utf-8'));meta['run_id']='old';self.meta.write_text(json.dumps(meta),encoding='utf-8')
        return state

    def test_own_chain_uses_exact_proof_and_does_not_invent_direct_glow_or_completion(self):
        before=copy.deepcopy(self.state);r,o=self.resolve()
        self.assertEqual(r.scene,'theater_list');self.assertEqual(r.episode,self.following)
        self.assertIn(7,r.completed);self.assertEqual((r.ticket_cost,r.ticket_stock),(1,11))
        self.assertIn('theater_reward_context:claim',o.visuals)
        self.assertNotIn('theater_season:1',o.visuals);self.assertEqual(self.state,before)

    def test_standalone_free_close_can_read_last_archive_but_never_restore_or_backfill_it(self):
        state=self.standalone();before=copy.deepcopy(state);r,o=self.resolve(state=state)
        self.assertEqual(r.episode,self.following);self.assertIn(7,r.completed)
        self.assertEqual(plan(r,state,'run'),'open');self.assertEqual(state,before)
        state['actions'].append(dict(kind='advance',run_id='run',status='sent'))
        r,o=self.resolve(state=state);self.assertIsNone(r.episode)
        self.assertNotIn('theater_reward_context:claim',o.visuals)

    def test_missing_tick_caption_identity_or_explicit_other_season_does_not_borrow(self):
        for change in ('tick','label','caption','logo','selected','other_season'):
            obs=copy.deepcopy(self.obs)
            if change=='tick':obs.visuals.discard('theater_complete:7')
            elif change=='label':obs.tokens=[t for t in obs.tokens if not(t.text=='完成' and 470<t.center[1]<490)]
            elif change=='caption':obs.tokens=[replace(t,text='第8集·别的故事') if t.text.startswith('第8集·') else t for t in obs.tokens]
            elif change=='logo':obs.tokens=[replace(t,text='别的') if t.text=='没落' else t for t in obs.tokens]
            elif change=='selected':obs.visuals={'theater_selected:9'}
            else:obs.visuals.add('theater_season:2')
            r,o=self.resolve(obs=obs)
            self.assertNotIn('theater_reward_context:claim',o.visuals,change)
        obs=copy.deepcopy(self.obs);obs.tokens.append(h.token('确认',800,500))
        r,o=self.resolve(obs=obs);self.assertEqual(r.scene,'theater_unknown_dialog')

    def test_unknown_duplicate_nonadjacent_foreign_or_wrong_archive_cannot_recover_context(self):
        for change in ('claim_unknown','close_unknown','duplicate','nonadjacent','foreign','phase','playback'):
            state=copy.deepcopy(self.state)
            if change=='claim_unknown':state['actions'][0]['status']='unknown'
            elif change=='close_unknown':state['actions'][1]['status']='unknown'
            elif change=='duplicate':state['actions'].insert(0,copy.deepcopy(state['actions'][0]))
            elif change=='nonadjacent':state['actions'].insert(1,dict(kind='open',status='sent'))
            elif change=='foreign':state['actions'][0]['run_id']='other'
            elif change=='phase':state['active']['phase']='await_ticket'
            else:del state['active']['playback_evidence']
            r,o=self.resolve(state=state);self.assertIsNone(r.episode,change)
        state=self.standalone();state['unresolved_entries'][-1]['entry']['key']='different'
        r,o=self.resolve(state=state);self.assertIsNone(r.episode)

    def test_missing_or_tampered_image_metadata_never_authorizes_context(self):
        original=self.meta.read_bytes()
        for change in ('hash','scene','run','season','null'):
            meta=json.loads(original)
            if change=='hash':meta['image_sha256']='bad'
            elif change=='scene':meta['scene']='theater_list'
            elif change=='run':meta['run_id']='other'
            elif change=='season':meta['visuals']=[v for v in meta['visuals'] if not v.startswith('theater_season:')]
            else:meta=None
            self.meta.write_text(json.dumps(meta),encoding='utf-8')
            r,o=self.resolve();self.assertIsNone(r.episode,change)
        self.meta.write_bytes(original);(self.root/'evidence/source.png').unlink()
        r,o=self.resolve();self.assertIsNone(r.episode)

    def test_actual_private_post_notice_directory_anchors_season_and_previous_clear(self):
        audit=Path(__file__).resolve().parents[1]/'.local/theater-normal-reward-20261105'
        image=audit.parent/'theater-stall-20261105/20261105T135751.png'
        if not image.is_file() or not(audit/'state.after-close.json').is_file():
            self.skipTest('未分发领奖后原生目录/证据私有素材')
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        with Image.open(image) as im:o=TheaterVision().apply(im,read_observation(im,ocr,time.monotonic()))
        state=json.loads((audit/'state.after-close.json').read_text(encoding='utf-8'));before=copy.deepcopy(state)
        run_id=state['actions'][-1]['run_id']
        r=reward_return_reading(o,classify(o),state,run_id,audit/'fixture-evidence')
        self.assertEqual(r.scene,'theater_list');self.assertEqual(r.episode,Episode('没落大地',3,2))
        self.assertEqual((r.ticket_cost,r.ticket_stock),(1,11));self.assertIn(2,r.completed)
        self.assertEqual(plan(r,state,run_id),'open')
        self.assertEqual(state,before)


    def test_worker_claim_transition_close_faded_season_complete_then_new_entry(self):
        first_im,first=directory(selected=7,completed=(5,6),stock=12)
        first=TheaterVision().apply(first_im,first)
        source_meta=json.loads(self.meta.read_text(encoding='utf-8'))
        from abyss_core import Observation
        source=Observation(1600,900,[Token(**t) for t in source_meta['tokens']],
                           visuals=set(source_meta['visuals']))
        transition=copy.deepcopy(source)
        transition.tokens=[t for t in transition.tokens if t.source!='theater_reward_claim']
        notice=h.observation([h.token('获得奖励',800,210),h.token('已领取奖励。',800,290),
                              h.token('若有未领取的观览奖励，则将汇总后统一领取。',800,315),
                              h.token('点击关闭',800,660)])
        transport,ctl,state=h.TheaterWorkerTests().run_frames([
            first,h.ticket(),h.guide(),h.observation(visuals=['theater_story']),
            self.partial_reward(source),source,transition,notice,copy.deepcopy(self.obs)])
        kinds=[a['kind'] for a in state['actions']]
        self.assertEqual(kinds.count('claim_reward'),1);self.assertEqual(kinds.count('close_reward_notice'),1)
        self.assertEqual(kinds.count('open'),2);self.assertEqual(kinds.count('ticket'),1)
        self.assertIn(self.old.key,state['completed'])
        self.assertEqual(state['active']['key'],self.following.key)
        ctl.attention.assert_not_called()


    def partial_reward(self,obs):
        obs=copy.deepcopy(obs)
        obs.visuals={v for v in obs.visuals if not v.startswith(('theater_season:','theater_selected:','theater_soft_selected:'))}
        return obs

    def test_result_return_wait_is_zero_input_only_and_known_controls_have_priority(self):
        from theater_worker import story_return_pending
        state=copy.deepcopy(self.state)
        state['actions']=[dict(kind='open',key=self.old.key,run_id='run',status='sent')]
        obs=copy.deepcopy(self.obs);reading=classify(obs)
        self.assertTrue(story_return_pending(obs,reading,state,'run'))
        for scene in ('theater_reward_ready','theater_reward_notice','theater_blocked',
                      'theater_unknown_dialog','theater_defeat','theater_story'):
            self.assertFalse(story_return_pending(obs,replace(reading,scene=scene),state,'run'))
        self.assertFalse(story_return_pending(obs,replace(reading,completed=(7,)),state,'run'))
        for change in ('wrong_run','no_play','unknown','duplicate','claimed','other_production','other_season','other_selected'):
            st=copy.deepcopy(state);o=copy.deepcopy(obs);r=reading
            if change=='wrong_run':st['active']['run_id']='other'
            elif change=='no_play':del st['active']['playback_evidence']
            elif change=='unknown':st['actions'][0]['status']='unknown'
            elif change=='duplicate':st['actions']*=2
            elif change=='claimed':st['actions'].append(dict(kind='claim_reward',key=self.old.key,status='sent'))
            elif change=='other_production':o.tokens=[replace(t,text='其他') if t.text=='没落' else t for t in o.tokens]
            elif change=='other_season':r=replace(reading,episode=Episode('没落大地',8,2))
            else:o.visuals={'theater_selected:20'}
            self.assertFalse(story_return_pending(o,r,st,'run'),change)

    def test_actual_private_result_return_failure_waits_without_changing_records(self):
        from theater_worker import story_return_pending
        from abyss_core import Observation
        audit=Path(__file__).resolve().parents[1]/'.local/theater-normal-reward-20261105'
        p=audit/'result-return-failure.json';sp=audit/'state.before-result-return-fix.json'
        if not p.is_file() or not sp.is_file():self.skipTest('未分发当前结果返回私有故障帧')
        meta=json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256(p.with_suffix('.png').read_bytes()).hexdigest(),meta['image_sha256'])
        obs=Observation(meta['width'],meta['height'],[Token(**t) for t in meta['tokens']],
                        meta['captured_at'],visuals=set(meta['visuals']))
        state=json.loads(sp.read_text(encoding='utf-8'));before=copy.deepcopy(state)
        self.assertTrue(story_return_pending(obs,classify(obs),state,state['active']['run_id']))
        self.assertEqual(state,before)


    def test_first_result_frame_without_selected_marker_only_waits_without_input(self):
        from theater_worker import story_return_pending
        state=copy.deepcopy(self.state)
        state['actions']=[dict(kind='open',key=self.old.key,run_id='run',status='sent')]
        obs=copy.deepcopy(self.obs)
        obs.visuals={v for v in obs.visuals if not v.startswith(('theater_selected:','theater_soft_selected:'))}
        self.assertIsNone(classify(obs).episode)
        self.assertTrue(story_return_pending(obs,classify(obs),state,'run'))
        for text in ('确认','购买门票','战斗失败'):
            other=copy.deepcopy(obs);other.tokens.append(h.token(text,800,500))
            self.assertFalse(story_return_pending(other,classify(other),state,'run'))

    def test_actual_private_post_clear_frame_without_outline_is_bounded_observation(self):
        from theater_worker import story_return_pending
        from abyss_core import Observation
        folder=Path(__file__).resolve().parents[1]/'.local/theater-two-wave-20261105'
        p=folder/'return-before-selection.json';sp=folder/'state.before-return-marker-fix.json'
        if not p.is_file() or not sp.is_file():self.skipTest('未分发消罩后无选框首帧私有素材')
        m=json.loads(p.read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256(p.with_suffix('.png').read_bytes()).hexdigest(),m['image_sha256'])
        o=Observation(m['width'],m['height'],[Token(**t) for t in m['tokens']],m['captured_at'],visuals=set(m['visuals']))
        state=json.loads(sp.read_text(encoding='utf-8'));before=copy.deepcopy(state)
        self.assertIsNone(classify(o).episode)
        self.assertTrue(story_return_pending(o,classify(o),state,state['active']['run_id']))
        self.assertEqual(state,before)
