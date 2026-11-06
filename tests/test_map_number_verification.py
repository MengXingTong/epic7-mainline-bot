import copy,time,unittest,json,os
from pathlib import Path
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

class DottedMapNumberTests(unittest.TestCase):
    def source(self,number='2'):
        f=era_map();w=f.words[2]
        w.update(text=number+'. 猎物lI',score=.82,x=172,y=291,
                 box=[[118,274],[250,274],[250,308],[118,308]])
        runner.cv2.putText(f.image,number+'.',(120,304),runner.cv2.FONT_HERSHEY_SIMPLEX,
                          .9,(245,245,245),2,runner.cv2.LINE_AA)
        return f

    def reads(self,number='2',tail=None):
        return Mock(side_effect=[([[number+'.',.93]],None),([[number+'.',.92]],None),
                                 ([[number,.999]],None),([[number,.999]],None)] if tail is None else
                                [([[number+'.',.93]],None),([[number+'.',.92]],None),*tail])

    def test_dotted_prefix_gets_two_independent_tight_reads_without_promoting_name(self):
        for number in ('1','2','8','12','29','99'):
            with self.subTest(number=number):
                f=self.source(number);before=copy.deepcopy(f.words[2]);ocr=self.reads(number)
                strengthen_map_stage_number(f,ocr)
                d,rows=runner.selected_node(f)
                self.assertIsNotNone(d)
                self.assertEqual(d['stage'],int(number));self.assertEqual(d['name_score'],.82)
                self.assertEqual(f.words[2]['text'],before['text'])
                self.assertEqual(f.words[2]['score'],before['score'])
                proof=f.words[2]['stage_number_verification']
                self.assertEqual(proof['crop_kind'],'current_numeric_glyphs')
                self.assertEqual(len(proof['scores']),2);self.assertEqual(ocr.call_count,4)

    def test_weak_disagreeing_punctuated_or_nonnumeric_tight_read_never_passes(self):
        for text,score in (('2',.979),('3',.999),('2.',.999),('2+',.999),('2',float('nan'))):
            with self.subTest(text=text,score=score):
                f=self.source();ocr=self.reads(tail=[([[text,score]],None),([['2',.999]],None)])
                strengthen_map_stage_number(f,ocr)
                self.assertIsNone(runner.selected_node(f)[0])
                self.assertNotIn('stage_number_verification',f.words[2])

    def test_broad_numeric_disagreement_does_not_fish_for_another_crop(self):
        f=self.source();ocr=Mock(side_effect=[([['2.',.93]],None),([['3.',.999]],None)])
        strengthen_map_stage_number(f,ocr)
        self.assertIsNone(runner.selected_node(f)[0]);self.assertEqual(ocr.call_count,2)

    def test_missing_extra_or_fragmented_digit_glyphs_do_not_get_more_ocr(self):
        for mode in ('missing','extra','fragmented'):
            with self.subTest(mode=mode):
                f=self.source();f.image[274:309,116:143]=22
                if mode=='extra':
                    runner.cv2.rectangle(f.image,(119,280),(122,302),(245,245,245),-1)
                    runner.cv2.rectangle(f.image,(130,280),(133,302),(245,245,245),-1)
                if mode=='fragmented':
                    runner.cv2.rectangle(f.image,(120,283),(126,291),(245,245,245),-1)
                ocr=self.reads();strengthen_map_stage_number(f,ocr)
                self.assertNotIn('stage_number_verification',f.words[2])
                self.assertEqual(ocr.call_count,2)

    def test_tight_number_proof_is_still_bound_to_current_pixels_time_and_number(self):
        for mode in ('pixels','time','number'):
            with self.subTest(mode=mode):
                f=self.source();strengthen_map_stage_number(f,self.reads())
                self.assertIsNotNone(runner.selected_node(f)[0])
                if mode=='pixels':
                    x1,y1,x2,y2=f.words[2]['stage_number_verification']['crop'];f.image[y1:y2,x1:x2]=0
                elif mode=='time':f.at+=.01
                else:f.words[2]['text']='3. changed'
                self.assertIsNone(runner.selected_node(f)[0])

    def test_unknown_popup_still_vetoes_both_prefix_paths(self):
        f=self.source();f.words.append(dict(text='点击关闭',score=.99,x=800,y=550,box=[]))
        ocr=self.reads();strengthen_map_stage_number(f,ocr)
        ocr.assert_not_called();self.assertNotIn('stage_number_verification',f.words[2])

    def test_optional_private_source_with_production_ocr_is_read_only(self):
        root=Path(os.environ.get('EPIC7_MAP_PREFIX_FIXTURE',str(Path(__file__).resolve().parents[1]/'.local/map-prefix-20261106/source')))
        if not (root/'source.png').is_file() or not (root/'source-ocr.json').is_file():
            self.skipTest('private map prefix screenshot/OCR unavailable')
        from rapidocr_onnxruntime import RapidOCR
        image=runner.cv2.imdecode(runner.np.frombuffer((root/'source.png').read_bytes(),runner.np.uint8),1)
        data=json.loads((root/'source-ocr.json').read_text(encoding='utf8'))
        f=runner.Frame(image,[(w['box'],w['text'],w['score']) for w in data['words']])
        self.assertIsNone(runner.Runner.__new__(runner.Runner).map_ticket(f)[0])
        original_words=copy.deepcopy(f.words)
        strengthen_map_stage_number(f,RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2))
        node,rows,proof=runner.Runner.__new__(runner.Runner).map_ticket(f)
        self.assertEqual(node['key'],'E5-C6-S2');self.assertEqual(proof,'未通关蓝色当前节点')
        source_scores=[w['score'] for w in original_words if w['text'].lstrip().startswith(str(node['stage'])+'.')]
        self.assertEqual(len(source_scores),1);self.assertEqual(node['name_score'],source_scores[0])
        self.assertFalse(node['clear_badge']);self.assertFalse(node['locked'])
        self.assertTrue(all(row['locked'] for row in rows if row['stage']>2))

if __name__=='__main__':unittest.main()
