"""Chapter reward OCR bootstrap and live observation policy; no device input."""
import copy,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
from tutorial_core import chapter_reward_layout,chapter_star_reward_plan
from tutorial_ocr import strengthen_chapter_reward_thresholds
from test_map_layout import frame
from task_blockers import TaskAttention


def reward(counter='18/27',tiers=(9,18,27),score=.976):
    f=frame([('Episode 4',156,44),('第4章命运交错之处',187,138),
             (counter,67,774),('准备战斗',1391,827),
             *[(str(n),x,773) for n,x in zip(tiers,(205,323,448))]])
    f.words[2]['score']=score
    runner.cv2.circle(f.image,(282,793),6,(0,100,240),-1)
    return f


def reads(*values):
    return Mock(side_effect=[([[text,score]],None) for text,score in values])


class ChapterCounterTests(unittest.TestCase):
    def test_weak_counter_bootstraps_existing_tier_readers_without_changing_raw_words(self):
        f=reward();original=copy.deepcopy(f.words)
        ocr=reads(('18/27',.999),('18/27',.998))
        strengthen_chapter_reward_thresholds(f,ocr)
        self.assertEqual(f.words[:len(original)],original)
        self.assertEqual(ocr.call_count,1)
        self.assertEqual(chapter_reward_layout(f)['count'],18)
        self.assertEqual(chapter_reward_layout(f)['tiers'],[9,18,27])
        self.assertEqual(chapter_star_reward_plan(f)['target']['x'],311)
        self.assertEqual(f.words[-1]['source'],'current_chapter_reward_counter_field_read')
        self.assertEqual(f.words[-1]['verification_scores'],[.999])
        self.assertEqual(f.words[-1]['original_counter'],original[2])
        self.assertTrue(all(c.kwargs==dict(use_det=False,use_cls=False) for c in ocr.call_args_list))
        strengthen_chapter_reward_thresholds(f,ocr)
        self.assertEqual(ocr.call_count,1)

    def test_arbitrary_counter_and_titleless_complete_layout(self):
        f=reward('14/21',(7,14,21));f.words=f.words[2:]
        ocr=reads(('14/21',.999),('14/21',.998))
        strengthen_chapter_reward_thresholds(f,ocr)
        self.assertEqual(chapter_reward_layout(f)['tiers'],[7,14,21])
        self.assertEqual(chapter_star_reward_plan(f)['target']['x'],311)

    def test_counter_mismatch_weak_or_malformed_current_read_never_authorizes(self):
        cases=[reads(('19/27',.999)),reads(('18/27',.979)),
               Mock(return_value=(None,None)),Mock(return_value=([['18/27',.999],['18/27',.999]],None))]
        for ocr in cases:
            with self.subTest(ocr=ocr):
                f=reward();original=copy.deepcopy(f.words)
                strengthen_chapter_reward_thresholds(f,ocr)
                self.assertEqual(f.words,original)
                self.assertIsNone(chapter_reward_layout(f))
                self.assertIsNone(chapter_star_reward_plan(f))

    def test_missing_ambiguous_out_of_bounds_or_invalid_anchors_never_reread(self):
        for kind in ('missing_counter','duplicate_counter','strong_duplicate','weak_counter','invalid_count',
                     'zero_total','missing_action','weak_action','duplicate_action','wrong_action_position','wrong_counter_position'):
            with self.subTest(kind=kind):
                f=reward()
                if kind=='missing_counter':f.words.pop(2)
                elif kind=='duplicate_counter':f.words.append(copy.deepcopy(f.words[2]))
                elif kind=='strong_duplicate':
                    duplicate=copy.deepcopy(f.words[2]);duplicate['score']=.999;f.words.extend([duplicate,copy.deepcopy(duplicate)])
                elif kind=='weak_counter':f.words[2]['score']=.849
                elif kind=='invalid_count':f.words[2]['text']='28/27'
                elif kind=='zero_total':f.words[2]['text']='0/0'
                elif kind=='missing_action':f.words.pop(3)
                elif kind=='weak_action':f.words[3]['score']=.979
                elif kind=='duplicate_action':f.words.append(copy.deepcopy(f.words[3]))
                elif kind=='wrong_action_position':f.words[3]['y']=880
                else:f.words[2]['y']=749
                ocr=Mock();strengthen_chapter_reward_thresholds(f,ocr);ocr.assert_not_called()

    def test_insufficient_count_missing_threshold_or_notification_is_still_not_a_claim(self):
        for kind in ('count','tier','notification'):
            f=reward('17/27' if kind=='count' else '18/27')
            if kind=='tier':f.words.pop(-1)
            if kind=='notification':f.image[:]=22
            text=f.words[2]['text'];ocr=reads((text,.999),(text,.999))
            # Missing tiers need additional OCR, but absent/weak results cannot fill them.
            if kind=='tier':ocr=Mock(side_effect=[([[text,.999]],None)]*2+[(None,None)]*10)
            strengthen_chapter_reward_thresholds(f,ocr)
            self.assertIsNone(chapter_star_reward_plan(f))


class ChapterRewardObservationTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.patch=patch.object(runner,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
        self.events=patch('runner.event');self.events.start();self.addCleanup(self.events.stop)

    def make_runner(self):
        r=runner.Runner.__new__(runner.Runner)
        r.s=dict(active=None,attempted={'old':{'at':'retained'}},completed={'done':{'evidence':'retained'}},
                 entry_dispatches={'old':[{'status':'sent'}]},last_cleared={'key':'done'})
        r.ticket=None;r.last_mode='';r.mode_since=time.time();r.run_id='chapter-reward-test'
        r.free_notices=Mock();r.story_open_ack=None;r.story=None
        r.save=Mock();r.action=Mock();r.evidence=Mock(return_value='independent-evidence.png')
        return r

    def test_pending_fields_observe_then_claim_automatically_and_preserve_entry_history(self):
        r=self.make_runner();protected=copy.deepcopy(r.s)
        for _ in range(3):
            self.assertEqual(r.step(reward()),(True,.25))
            self.assertEqual(r.observation_wait['code'],'chapter_reward')
            self.assertNotIn('attention',r.s)
            r.action.assert_not_called()
        self.assertEqual(r.s['evidence_observations']['chapter_reward']['observations'],3)
        # A strong independent new frame progresses without a resume command.
        f=reward(score=.999);r.frame=f
        r.step(f)
        self.assertIsNone(r.observation_wait)
        r.action.assert_called_once()
        self.assertEqual(r.action.call_args.args[1]['x'],311)
        self.assertEqual(r.s['tutorial']['actions'][-1]['status'],'sent')
        r.step(reward(score=.999))
        self.assertEqual(r.action.call_count,1)
        for key,value in protected.items():self.assertEqual(r.s[key],value)

    def test_critical_persistence_error_is_never_swallowed(self):
        r=self.make_runner();r.save.side_effect=OSError('critical state write failed')
        with self.assertRaises(OSError):r.step(reward())
        r.action.assert_not_called()

    def test_unknown_modal_and_capacity_keep_their_higher_priority(self):
        for controls,code in (([('确认',900,500),('取消',700,500)],'dialog'),
                              ([('装备背包已满',800,500)],'equipment')):
            r=self.make_runner();f=reward()
            f.words.extend(frame(controls).words)
            with self.assertRaises(TaskAttention) as caught:r.step(f)
            self.assertEqual(caught.exception.code,code)
            self.assertIsNone(r.observation_wait)
            r.action.assert_not_called()


if __name__=='__main__':unittest.main()
