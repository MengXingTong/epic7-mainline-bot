"""Weak inventory text is refined locally, never by reducing paid-input guards."""
import copy,time,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from theater_core import classify,plan
from theater_ticket_ocr import refine_ticket_stock,SOURCE
from theater_worker import read_observation
from theater_vision import TheaterVision
from task_blockers import TaskAttention
from test_theater_ticket import immediate_dialog
import test_theater as h


def result(value=7,score=.92):
    return ([[[75,35],[369,35],[369,142],[75,142]],f'持有 : {value}',score])


class TicketStockRefinementTests(unittest.TestCase):
    def refine(self,obs=None,results=None):
        obs=immediate_dialog(stock=7) if obs is None else obs
        obs.tokens[5]=replace(obs.tokens[5],score=.842)
        ocr=Mock(side_effect=[([result()],None),([result(score=.916)],None)] if results is None else results)
        before=copy.deepcopy(obs.tokens)
        obs.tokens=refine_ticket_stock(Image.new('RGB',(1600,900)),obs.tokens,obs.width,obs.height,ocr)
        return obs,ocr,before

    def test_two_consistent_stronger_reads_retain_original_and_still_require_entry_chain(self):
        obs,ocr,before=self.refine();self.assertEqual(ocr.call_count,2)
        self.assertEqual(obs.tokens[:len(before)],before)
        refined=[t for t in obs.tokens if t.source==SOURCE];self.assertEqual(len(refined),1)
        self.assertGreaterEqual(refined[0].score,.90)
        r=classify(obs);self.assertEqual(r.scene,'theater_ticket');self.assertEqual((r.ticket_cost,r.ticket_stock),(1,7))
        with self.assertRaises(TaskAttention):plan(r,{'active':None},'run')
        with self.assertRaises(TaskAttention):plan(r,{'active':dict(run_id='old',phase='await_ticket')},'run')
        self.assertEqual(plan(r,{'active':dict(run_id='run',phase='await_ticket')},'run'),'ticket')

    def test_generic_inventory_values_not_a_seven_only_exception(self):
        for n in (0,1,7,8,12,99,100000,999999):
            obs=immediate_dialog(stock=n)
            obs,_,_=self.refine(obs,results=[([result(n)],None),([result(n,.91)],None)])
            r=classify(obs)
            self.assertEqual(r.scene,'theater_blocked' if n==0 else 'theater_ticket')
            if n:self.assertEqual(r.ticket_stock,n)

    def test_confident_primary_has_no_extra_ocr_and_duplicate_field_never_refines(self):
        for duplicate in (False,True):
            obs=immediate_dialog()
            if duplicate:obs.tokens.append(replace(obs.tokens[5],score=.3))
            ocr=Mock();original=copy.deepcopy(obs.tokens)
            self.assertEqual(refine_ticket_stock(Image.new('RGB',(1600,900)),obs.tokens,1600,900,ocr),original)
            ocr.assert_not_called()

    def test_disagreement_weak_missing_duplicate_or_bad_crop_has_no_new_token(self):
        cases=[([([result(7)],None),([result(8)],None)]),
               ([([result(8)],None),([result(8)],None)]),
               ([([result(7,.89)],None),([result(7,.89)],None),([],None)]),
               ([([],None)]),
               ([([result(7),result(7)],None)]),
               ([([result('?')],None)]),
               ([([[[[900,35],[1000,35],[1000,142],[900,142]],'持有7',.99]],None)])]
        for results in cases:
            obs,_,before=self.refine(results=results)
            self.assertEqual(obs.tokens,before)
            self.assertNotEqual(classify(obs).scene,'theater_ticket')

    def test_missing_weak_wrong_cost_or_misplaced_title_question_does_not_crop(self):
        for change in ('missing_title','weak_question','wrong_cost','wrong_position'):
            obs=immediate_dialog();obs.tokens[5]=replace(obs.tokens[5],score=.842)
            if change=='missing_title':obs.tokens.pop(0)
            elif change=='weak_question':obs.tokens[2]=replace(obs.tokens[2],score=.3)
            elif change=='wrong_cost':obs.tokens[2]=replace(obs.tokens[2],text='确定要使用2张剧场门票来立即观览吗？')
            else:obs.tokens[0]=replace(obs.tokens[0],y=10)
            ocr=Mock();original=copy.deepcopy(obs.tokens)
            self.assertEqual(refine_ticket_stock(Image.new('RGB',(1600,900)),obs.tokens,1600,900,ocr),original)
            ocr.assert_not_called()

    def test_resource_defeat_extra_confirmation_and_duplicate_refinement_still_block(self):
        obs,_,_=self.refine()
        for text in ('购买门票','其他道具','战斗失败','确认'):
            other=copy.deepcopy(obs);other.tokens.append(h.token(text,800,500,score=.3))
            self.assertNotEqual(classify(other).scene,'theater_ticket')
        other=copy.deepcopy(obs);other.tokens.append(next(t for t in other.tokens if t.source==SOURCE))
        self.assertNotEqual(classify(other).scene,'theater_ticket')
        other=copy.deepcopy(obs);other.tokens[5]=replace(other.tokens[5],text='持有8')
        self.assertNotEqual(classify(other).scene,'theater_ticket')

    def test_native_actual_weak_stock_dialog_refines_but_no_active_never_spends(self):
        p=Path(__file__).resolve().parents[1]/'.local/theater-stock-20261105/before.png'
        if not p.is_file():self.skipTest('未分发实机弱库存私有画面')
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        with Image.open(p) as im:obs=TheaterVision().apply(im,read_observation(im,ocr,time.monotonic()))
        stocks=[t for t in obs.tokens if t.text.replace(' ','').startswith('持有')]
        self.assertTrue(any(t.source!=SOURCE and t.score<.85 for t in stocks))
        self.assertEqual(len([t for t in stocks if t.source==SOURCE]),1)
        r=classify(obs);self.assertEqual(r.scene,'theater_ticket');self.assertEqual((r.ticket_cost,r.ticket_stock),(1,7))
        with self.assertRaises(TaskAttention):plan(r,{'active':None},'new-run')


    def test_split_label_and_numeric_reads_are_generic_stricter_and_preserve_primary(self):
        for n in (0,1,2,3,4,5,6,7,8,9,10,12,99,123456,999999):
            split=[([([ [80,40],[240,40],[240,140],[80,140] ],'持有',.999)],None),
                   ([([ [40,50],[100,50],[100,130],[40,130] ],str(n),.999)],None)]
            results=[([result(n,.86)],None),([result(n,.87)],None)]+split+split
            obs,ocr,before=self.refine(immediate_dialog(stock=n),results)
            self.assertEqual(ocr.call_count,6);self.assertEqual(obs.tokens[:-1],before)
            r=classify(obs);self.assertEqual(r.scene,'theater_blocked' if n==0 else 'theater_ticket')
            if n:self.assertEqual(r.ticket_stock,n)
        for mode in ('label','digit','weak','duplicate','bounds'):
            results=copy.deepcopy([([result(6,.86)],None),([result(6,.87)],None)]+split+split)
            # Build exact stock6 numeric outputs, then corrupt one field.
            results[3][0][0]=(results[3][0][0][0],'6',.999)
            results[5][0][0]=(results[5][0][0][0],'6',.999)
            if mode=='label':results[2][0][0]=(results[2][0][0][0],'库存',.999)
            elif mode=='digit':results[5][0][0]=(results[5][0][0][0],'8',.999)
            elif mode=='weak':results[5][0][0]=(results[5][0][0][0],'6',.979)
            elif mode=='duplicate':results[5][0].append(copy.deepcopy(results[5][0][0]))
            else:results[5][0][0]=([[0,0],[999,0],[999,100],[0,100]],'6',.999)
            obs,_,before=self.refine(immediate_dialog(stock=6),results)
            self.assertEqual(obs.tokens,before)

    def test_private_stock_six_split_refines_without_digit_specific_branch(self):
        import hashlib,json
        folder=Path(__file__).resolve().parents[1]/'.local/theater-stock-20261105'
        p=folder/'stock6.png';meta=folder/'stock6-fixture.json'
        if not p.is_file() or not meta.is_file():self.skipTest('未分发库存6私有画面')
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),json.loads(meta.read_text(encoding='utf-8'))['image_sha256'])
        from rapidocr_onnxruntime import RapidOCR
        with Image.open(p) as im:
            obs=read_observation(im,RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2),time.monotonic())
        refined=[t for t in obs.tokens if t.source==SOURCE]
        self.assertEqual(len(refined),1);self.assertGreaterEqual(refined[0].score,.98)
        r=classify(obs);self.assertEqual((r.scene,r.ticket_cost,r.ticket_stock),('theater_ticket',1,6))
        with self.assertRaises(TaskAttention):plan(r,{'active':None},'new-run')

    def test_portable_allowlist_contains_refiner_but_no_private_fixtures(self):
        from build_portable import SOURCES
        self.assertEqual(SOURCES.count('theater_ticket_ocr.py'),1)
        self.assertTrue(all(not s.startswith('.local') for s in SOURCES))
