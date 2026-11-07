"""Whole map-label readings survive detector overlap without relaxing matching."""
import copy,hashlib,unittest,time
from pathlib import Path
from unittest.mock import Mock,patch
import runner
from tutorial_ocr import strengthen_map_row_label
from test_map_layout import map_frame,fake_runner

class WholeMapLabelTests(unittest.TestCase):
    def fixture(self):
        f=map_frame();w=f.words[2]
        w.update(text='5.梦想、',x=178.5,y=291.,box=[[120.,276.],[237.,276.],[237.,306.],[120.,306.]])
        f.words.append(dict(text='迷恋与真实3',score=.99,x=309.5,y=290.5,box=[[231.,277.],[388.,277.],[388.,304.],[231.,304.]]))
        return f
    def ocr(self,text='5.梦想、迷恋与真实3',score=.995):return Mock(return_value=([[text,score]],None))
    def test_overlapping_detector_fragments_use_full_field_field_read(self):
        f=self.fixture();raw=[(w['text'],w['score'],copy.deepcopy(w['box'])) for w in f.words];ocr=self.ocr()
        strengthen_map_row_label(f,ocr);d,_,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
        self.assertEqual(d['name'],'梦想、迷恋与真实3');self.assertEqual(len(d['name_verification']['scores']),1)
        self.assertEqual(raw,[(w['text'],w['score'],w['box']) for w in f.words]);self.assertEqual(ocr.call_count,1)
        self.assertTrue(all(c.kwargs==dict(use_det=False,use_cls=False) for c in ocr.call_args_list))
    def test_different_number_prefix_score_or_disagreeing_reads_cannot_promote(self):
        for mode in ('number','prefix','score'):
            f=self.fixture();ocr=self.ocr()
            if mode=='number':ocr=self.ocr('6.梦想、迷恋与真实3')
            elif mode=='prefix':ocr=self.ocr('5.另一节点')
            elif mode=='score':ocr=self.ocr(score=.979)
            else:ocr.side_effect=[([['5.梦想、迷恋与真实3',.995]],None),([['5.梦想、迷恋与真实2',.995]],None)]
            strengthen_map_row_label(f,ocr);d,_,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
            self.assertEqual(d['name'],'梦想、');self.assertIs(d.get('name_complete'),False)
    def test_stale_or_changed_pixel_proof_cannot_be_reused(self):
        for mode in ('time','pixels','hash','score','anchor'):
            f=self.fixture();strengthen_map_row_label(f,self.ocr());proof=f.words[2]['stage_label_verification']
            if mode=='time':proof['captured_at']-=1
            elif mode=='pixels':f.image[280,250]=255
            elif mode=='hash':proof['crop_sha256']='bad'
            elif mode=='score':proof['scores'][0]=.97
            else:proof['anchor_text']='other'
            d,_,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
            self.assertEqual(d['name'],'梦想、')
    def test_weak_suffix_can_only_be_replaced_by_independent_high_confidence_pixels(self):
        f=self.fixture();f.words[-1]['score']=.6
        strengthen_map_row_label(f,self.ocr());d,_,_=runner.Runner.__new__(runner.Runner).map_ticket(f)
        self.assertEqual(d['name'],'梦想、迷恋与真实3');self.assertEqual(f.words[-1]['score'],.6)
    def test_duplicate_overlapping_alternatives_do_not_form_a_title(self):
        f=self.fixture();f.words.append(copy.deepcopy(f.words[-1]));ocr=self.ocr()
        strengthen_map_row_label(f,ocr);self.assertNotIn('stage_label_verification',f.words[2]);ocr.assert_not_called()
    def test_incomplete_name_observes_on_map_then_progresses_after_field_is_read(self):
        f=self.fixture();strengthen_map_row_label(f,self.ocr(score=.97));r=fake_runner(f);r.run_id='known-run'
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-whole-label-test')):
            keep,_=r.step(f);self.assertTrue(keep);r.action.assert_not_called()
            self.assertEqual(r.observation_wait['code'],'map_title');self.assertEqual(r.s['attempted'],{})
            strengthen_map_row_label(f,self.ocr());keep,_=r.step(f)
        self.assertTrue(keep);self.assertEqual(r.ticket['name'],'梦想、迷恋与真实3')
        self.assertEqual(r.action.call_args.args[0],'未通关验证通过，准备战斗')
    def test_current_map_result_label_still_requires_full_support_name(self):
        f=self.fixture();strengthen_map_row_label(f,self.ocr());r=fake_runner(f);r.ticket=r.map_ticket(f)[0]
        good=copy.deepcopy(f);good.words=[dict(text='梦想、迷恋与真实3',score=.999,x=1250,y=160,box=[])]
        bad=copy.deepcopy(good);bad.words[0]['text']='完全不同关卡'
        self.assertTrue(r.title_matches(good));self.assertFalse(r.title_matches(bad))

if __name__=='__main__':unittest.main()
