"""Penguin mode offline safety: synthetic tokens only, no game input."""
import copy
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from abyss_core import Observation,Token
from penguin_core import Reading,Action,classify,plan,quantity
from penguin_journal import PenguinJournal
from penguin_vision import same_currency
from task_blockers import TaskAttention

CURRENCY='0'*80+'1'*100+'0'*76
BINDING={'window':'same-window','geometry':[0,0,1064,599]}
BUY=Token('购买',640,800,40,20,score=.999)
OTHER=Token('购买',850,800,40,20,score=.999)
MIN=Token('最少',280,650,40,20,score=.999)
MAX=Token('最多',700,650,40,20,score=.999)
PLUS=Token('+1',640,650,30,20,score=.999)
MINUS=Token('-1',330,650,30,20,score=.999)
CANCEL=Token('取消',350,800,40,20,score=.999)

def altar(stock=100000,unit=102):
    return Reading('penguin_altar',BUY,stock=stock,unit=unit,currency=CURRENCY)

def dialog(n=1,m=50,total=None):
    return Reading('penguin_dialog',BUY,selected=n,maximum=m,total=n*102 if total is None else total,
        currency=CURRENCY,minimum=MIN,most=MAX,plus=PLUS,minus=MINUS,cancel=CANCEL)

def tok(text,x,y,score=.999):return Token(text,x*1000-15,y*1000-10,30,20,score=score)

def modal_tokens():
    return [tok('购买商品',.5,.175),tok('确定要购买该商品吗？',.5,.28),tok('英雄升等材料',.55,.395),
        tok('企鹅巢穴',.55,.435),tok('购买',.65,.82),tok('取消',.365,.82),tok('最少',.29,.655),
        tok('最多',.71,.655),tok('1/50',.5,.60),tok('102',.54,.82),tok('+1',.65,.655),tok('-1',.35,.655)]

class RecognitionTests(unittest.TestCase):
    def observe(self,tokens):return Observation(1000,1000,tokens,visuals={'penguin_currency:'+CURRENCY})
    def test_exact_modal_fields(self):
        r=classify(self.observe(modal_tokens()))
        self.assertEqual(r.scene,'penguin_dialog');self.assertEqual(r.selected,1)
        self.assertEqual(r.maximum,50);self.assertEqual(r.total,102)
    def test_missing_or_low_confidence_field_never_buys(self):
        for index in range(10):
            rows=modal_tokens();rows[index]=replace(rows[index],score=.97)
            self.assertEqual(classify(self.observe(rows)).scene,'penguin_unknown',index)
        for index in range(10):
            rows=modal_tokens();rows.pop(index)
            self.assertEqual(classify(self.observe(rows)).scene,'penguin_unknown',index)
    def test_flower_modal_duplicate_price_or_quantity_rejected(self):
        for name in ('下级精灵之花','企鹅','企鹅巢穴礼包'):
            rows=modal_tokens();rows[3]=replace(rows[3],text=name)
            self.assertEqual(classify(self.observe(rows)).scene,'penguin_unknown')
        for extra in (tok('103',.55,.82),tok('2/50',.51,.60),tok('购买',.66,.82)):
            self.assertEqual(classify(self.observe(modal_tokens()+[extra])).scene,'penguin_unknown')
    def test_currency_missing_unknown_and_capacity_veto(self):
        o=self.observe(modal_tokens());o.visuals.clear()
        self.assertEqual(classify(o).scene,'penguin_unknown')
        with self.assertRaises(TaskAttention):classify(self.observe(modal_tokens()+[tok('英雄栏已满',.5,.4)]))
        with self.assertRaises(TaskAttention):classify(self.observe(modal_tokens()+[tok('行动力不足',.5,.4)]))
    def test_unknown_confirmation_or_close_over_known_purchase_zero_input(self):
        for text in ('确认','确定','点击关闭'):
            self.assertEqual(classify(self.observe(modal_tokens()+[tok(text,.5,.5)])).scene,'penguin_unknown')

    def test_dialog_has_precedence_over_altar(self):
        rows=modal_tokens()+[tok('成长祭坛',.11,.225),tok('精灵之泉',.61,.31)]
        self.assertEqual(classify(self.observe(rows)).scene,'penguin_dialog')
    def test_inconsistent_selected_maximum_unknown(self):
        rows=modal_tokens();rows[8]=replace(rows[8],text='51/50')
        self.assertEqual(classify(self.observe(rows)).scene,'penguin_unknown')

class PlanTests(unittest.TestCase):
    baseline=dict(stock=100000,unit=102,currency=CURRENCY)
    def p(self,r,remaining=50,phase='opening',baseline=None,pending=None):
        return plan(r,phase,remaining,self.baseline if baseline is None else baseline,pending)
    def test_total_quantity_strict(self):
        for value in ('',None,False,True,0,-1,'0','01',1.2,'1.0','-2','1e2',' 1','１','1000000'):
            with self.assertRaises(ValueError):quantity(value)
        for value in (1,'50',999999):self.assertEqual(quantity(value),int(value))
    def test_full_batch_uses_most_and_never_exceeds_requested(self):
        self.assertEqual(self.p(dialog(),remaining=123).kind,'most')
        a=self.p(dialog(50),remaining=123);self.assertEqual((a.kind,a.desired),('purchase',50))
        self.assertEqual(self.p(dialog(50),remaining=49).kind,'minus')
        self.assertEqual(self.p(dialog(49),remaining=49).desired,49)
        self.assertEqual(self.p(dialog(50),remaining=1).kind,'minimum')
    def test_tail_batch_shortest_path_and_actual_max_not_hardcoded(self):
        self.assertEqual(self.p(dialog(1,m=20),remaining=50).kind,'most')
        self.assertEqual(self.p(dialog(20,m=20),remaining=50).desired,20)
        self.assertEqual(self.p(dialog(1),remaining=2).kind,'plus')
        self.assertEqual(self.p(dialog(10),remaining=2).kind,'minimum')
        self.assertEqual(self.p(replace(dialog(1),plus=None),remaining=2).kind,'wait')
    def test_start_on_existing_dialog_only_cancels(self):
        a=self.p(dialog(),phase='navigate');self.assertEqual(a.kind,'cancel')
    def test_price_currency_inventory_errors_never_buy(self):
        for r in (dialog(total=103),replace(dialog(),currency='1'*256)):
            with self.assertRaises(TaskAttention):self.p(r)
        with self.assertRaises(TaskAttention):self.p(dialog(),baseline=dict(self.baseline,stock=1))
        with self.assertRaises(TaskAttention):self.p(altar(1),phase='navigate')
    def test_pending_intent_and_unknown_sent_never_repeat(self):
        for status in ('intent','sent','not_sent','unknown'):
            self.assertEqual(self.p(dialog(50),pending={'status':status}).kind,'wait_result')
    def test_unknown_no_target_and_no_cross_chain_reopen(self):
        self.assertEqual(self.p(Reading()).kind,'wait')
        self.assertEqual(self.p(altar()).kind,'wait')
        with self.assertRaises(TaskAttention):self.p(Reading('penguin_lobby',BUY))
    def test_currency_descriptor_rejects_empty_blue_and_different_shapes(self):
        self.assertTrue(same_currency(CURRENCY,CURRENCY))
        for value in (None,'','0'*256,'1'*256):self.assertFalse(same_currency(CURRENCY,value))

class JournalTests(unittest.TestCase):
    evidence={'image':'local.png','metadata':'local.json','image_sha256':'x','metadata_sha256':'y'}
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.j=PenguinJournal(self.root,'run',51)
    def purchase(self,n=50):
        j=self.j;id=j.reserve(Action('open',BUY),altar(),self.evidence,BINDING);j.sent(id,'sent')
        id=j.reserve(Action('purchase',BUY,n),dialog(n),self.evidence,BINDING)
        return id
    def test_independent_exact_balance_and_same_binding_required(self):
        id=self.purchase();self.j.sent(id,'sent')
        self.assertFalse(self.j.confirm(altar(),self.evidence,BINDING))
        with self.assertRaises(TaskAttention):self.j.confirm(altar(100000-5100),self.evidence,dict(BINDING,window='other'))
        with self.assertRaises(TaskAttention):self.j.confirm(altar(100000-5099),self.evidence,BINDING)
        self.assertEqual(self.j.run['purchased'],0)
        self.assertTrue(self.j.confirm(altar(94900),self.evidence,BINDING))
        self.assertEqual(self.j.run['purchased'],50);self.assertEqual(self.j.remaining,1)
        self.assertEqual(self.j.state['actions'][-1]['status'],'sent')
        self.assertEqual(len(self.j.state['purchases']),1);self.assertIsNone(self.j.pending)
    def test_no_intent_unknown_or_not_sent_can_be_marked_success(self):
        for status in ('intent','unknown','not_sent'):
            with tempfile.TemporaryDirectory() as folder:
                j=PenguinJournal(folder,'run',50);opened=j.reserve(Action('open',BUY),altar(),self.evidence,BINDING);j.sent(opened,'sent')
                ident=j.reserve(Action('purchase',BUY,50),dialog(50),self.evidence,BINDING)
                if status!='intent':j.sent(ident,status)
                self.assertFalse(j.confirm(altar(94900),self.evidence,BINDING))
                with self.assertRaises(ValueError):j.reserve(Action('purchase',BUY,50),dialog(50),self.evidence,BINDING)
                with self.assertRaises(TaskAttention):PenguinJournal(folder,'newrun',50)
    def test_failure_to_save_intent_must_propagate(self):
        with patch('penguin_journal.atomic_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.j.reserve(Action('open',BUY),altar(),self.evidence,BINDING)
    def test_order_quantity_never_rewritten_or_overbought(self):
        self.purchase();
        with self.assertRaises(ValueError):PenguinJournal(self.root,'run',52)
        self.j.state['pending']=None
        with self.assertRaises(ValueError):self.j.reserve(Action('purchase',BUY,52),dialog(52,m=60),self.evidence,BINDING)
    def test_missing_unsent_or_wrong_binding_open_never_authorizes_purchase(self):
        with self.assertRaises(ValueError):self.j.reserve(Action('purchase',BUY,50),dialog(50),self.evidence,BINDING)
        ident=self.j.reserve(Action('open',BUY),altar(),self.evidence,BINDING)
        with self.assertRaises(ValueError):self.j.reserve(Action('purchase',BUY,50),dialog(50),self.evidence,BINDING)
        self.j.sent(ident,'sent')
        with self.assertRaises(ValueError):self.j.reserve(Action('purchase',BUY,50),dialog(50),self.evidence,dict(BINDING,window='other'))
        with self.assertRaises(ValueError):self.j.reserve(Action('purchase',OTHER,50),dialog(50),self.evidence,BINDING)

    def test_corrupted_pending_or_duplicate_success_not_reset(self):
        self.purchase()
        self.j.state['pending']=dict(self.j.pending,quantity=51);self.j.save()
        before=self.j.path.read_bytes()
        with self.assertRaises(ValueError):PenguinJournal(self.root,'run',51)
        self.assertEqual(self.j.path.read_bytes(),before)

    def test_existing_mainline_history_untouched(self):
        p=self.root/'state.json';p.write_text('{"attempted":{"old":"sent"},"active":{"key":"failed"}}')
        before=p.read_bytes();self.purchase();self.assertEqual(p.read_bytes(),before)
    def test_old_successes_kept_new_order_not_empty_history(self):
        id=self.purchase();self.j.sent(id,'sent');self.j.confirm(altar(94900),self.evidence,BINDING)
        new=PenguinJournal(self.root,'run2',1)
        self.assertEqual(len(new.state['purchases']),1);self.assertIn('run',new.state['runs'])
        self.assertEqual(new.state['runs']['run']['purchased'],50)

if __name__=='__main__':unittest.main()
