import copy,time,unittest
from unittest.mock import Mock
import runner
from tutorial_ocr import strengthen_map_stage_number
from test_era_map import era_map
class MapNumberTests(unittest.TestCase):
    def source(self):
        f=era_map();f.words[2]['score']=.846;return f
    def test_numeric_prefix_is_independent_and_does_not_forge_name_score(self):
        f=self.source();word=f.words[2];old=copy.deepcopy(word);ocr=Mock(return_value=([['2',.999]],None))
        strengthen_map_stage_number(f,ocr);d,rows=runner.selected_node(f)
        self.assertEqual(d['stage'],2);self.assertEqual(d['name_score'],.846)
        self.assertEqual(word['text'],old['text']);self.assertEqual(word['score'],old['score']);self.assertEqual(ocr.call_count,2)
    def test_bad_low_disagreeing_or_not_numeric_reads_do_not_promote_row(self):
        for readings in (([['3',.999]],[['3',.999]]),([['2',.979]],[['2',.999]]),([['2',.999]],[['3',.999]]),([['2+',.999]],[['2',.999]])):
            f=self.source();ocr=Mock(side_effect=[(readings[0],None),(readings[1],None)])
            strengthen_map_stage_number(f,ocr);self.assertIsNone(runner.selected_node(f)[0])
    def test_unknown_popup_or_nonselected_row_has_no_reread(self):
        f=self.source();f.words.append(dict(text='点击关闭',score=.99,x=800,y=550,box=[]));ocr=Mock()
        strengthen_map_stage_number(f,ocr);ocr.assert_not_called()
        f=self.source();f.image[:]=22;strengthen_map_stage_number(f,ocr);ocr.assert_not_called()
    def test_changed_pixels_or_new_capture_time_invalidate_number_proof(self):
        for change in ('image','time','number'):
            f=self.source();strengthen_map_stage_number(f,Mock(return_value=([['2',.999]],None)))
            if change=='image':
                x1,y1,x2,y2=f.words[2]['stage_number_verification']['crop'];f.image[y1:y2,x1:x2]=[0,0,1]
            if change=='time':f.at+=.1
            if change=='number':f.words[2]['text']='3.changed'
            self.assertIsNone(runner.selected_node(f)[0])
if __name__=='__main__':unittest.main()
