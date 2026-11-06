"""Full worker with fake transport: exercises batching and never calls Windows APIs."""
import contextlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from abyss_core import Observation
from assistant_transport import FrameSnapshot
from assistant_worker import StopRun
from pc_backend import TapNotSent
from penguin_journal import PenguinJournal
from penguin_worker import run
from test_penguin import altar,dialog,Reading,BINDING

class Control:
    def __init__(self):self.calls=0;self.inputs=[];self.statuses=[];self.attentions=[]
    def check(self):
        self.calls+=1
        if self.calls>1500:raise AssertionError('worker did not stop')
    def preview(self,image):pass
    def status(self,*args,**kw):self.statuses.append((args,kw))
    def sleep(self,n):pass
    def log(self,*args):pass
    def attention(self,exc):self.attentions.append(exc);raise StopRun()
    def paused(self):pass

class Transport:
    def __init__(self,readings,fail_on=None):
        self.readings=iter(readings);self.reading=None;self.inputs=[];self.fail_on=fail_on
    def ensure(self):return BINDING
    def capture(self):
        self.reading=next(self.readings,self.reading)
        return FrameSnapshot(Image.new('RGB',(16,9),'white'),BINDING,time.monotonic())
    def tap(self,snap,token):
        self.inputs.append(token.text)
        if len(self.inputs)==self.fail_on:raise TapNotSent('mouse took over before down')

class WorkerTests(unittest.TestCase):
    def exercise(self,rows,count,fail_on=None,clock=None):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        transport=Transport(rows,fail_on);control=Control()
        request=dict(run_id='worker-run',settings=dict(task='penguin',penguin_quantity=count),target={'client':'pc'})
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch('assistant_config.validate_run',return_value=(root,{})))
            stack.enter_context(patch('assistant_transport.UnifiedTransport',return_value=transport))
            stack.enter_context(patch('rapidocr_onnxruntime.RapidOCR',return_value=object()))
            stack.enter_context(patch('penguin_worker.read_observation',side_effect=lambda *a:Observation(1000,1000,[])))
            stack.enter_context(patch('penguin_worker.classify',side_effect=lambda o:transport.reading))
            if clock:stack.enter_context(patch('penguin_worker.time.monotonic',side_effect=clock))
            try:run(request,control)
            except StopRun:pass
        import json
        state=json.loads((root/'penguin/state.json').read_text(encoding='utf8'))
        return transport,control,state,root
    def test_51_exactly_two_batches_50_then_1_no_extra_purchase(self):
        rows=[altar()]*2+[dialog()]*2+[dialog(50)]*2+[altar(94900)]*4+[dialog()]*2+[altar(94798)]*3
        t,c,s,_=self.exercise(rows,51)
        self.assertEqual(t.inputs,['购买','最多','购买','购买','购买'])
        self.assertEqual([p['quantity'] for p in s['purchases']],[50,1])
        self.assertEqual(s['runs']['worker-run']['purchased'],51);self.assertIsNone(s['pending'])
        self.assertEqual(c.statuses[-1][1]['mode'],'done')
    def test_tail_49_uses_most_then_minus_and_not_50(self):
        rows=[altar()]*2+[dialog()]*2+[dialog(50)]*2+[dialog(49)]*2+[altar(95002)]*3
        t,c,s,_=self.exercise(rows,49)
        self.assertEqual(t.inputs,['购买','最多','-1','购买'])
        self.assertEqual(s['purchases'][0]['quantity'],49)
    def test_mouse_takeover_at_final_purchase_leaves_not_sent_pending_no_retry(self):
        ticks=iter(range(10000))
        t,c,s,root=self.exercise([altar()]*2+[dialog()]*2+[dialog(50)]*2,50,fail_on=3)
        self.assertEqual(t.inputs,['购买','最多','购买']);self.assertEqual(s['pending']['status'],'not_sent')
        self.assertFalse(s['purchases']);self.assertEqual(c.attentions[-1].code,'penguin_not_sent')
        from task_blockers import TaskAttention
        with self.assertRaises(TaskAttention):PenguinJournal(root,'other',50)
    def test_unknown_screen_zero_input(self):
        ticks=iter(x*.1 for x in range(10000))
        t,c,s,_=self.exercise([Reading()],50,clock=lambda:next(ticks))
        self.assertEqual(t.inputs,[]);self.assertFalse(s['actions']);self.assertEqual(c.attentions[-1].code,'penguin_unknown')
    def test_same_purchase_dialog_after_dispatch_never_buys_twice(self):
        ticks=iter(x*.1 for x in range(10000))
        rows=[altar()]*2+[dialog()]*2+[dialog(50)]*2
        t,c,s,_=self.exercise(rows,50,clock=lambda:next(ticks))
        self.assertEqual(t.inputs,['购买','最多','购买']);self.assertEqual(s['pending']['status'],'sent')
        self.assertEqual(s['purchases'],[]);self.assertEqual(c.attentions[-1].code,'penguin_result')
    def test_unexpected_slider_change_does_not_purchase(self):
        t,c,s,_=self.exercise([altar()]*2+[dialog()]*2+[dialog(15)]*2,49)
        self.assertEqual(t.inputs,['购买','最多']);self.assertFalse(s['purchases'])
        self.assertEqual(c.attentions[-1].code,'penguin_quantity_change')
    def test_insufficient_total_budget_zero_input_not_partial_buy(self):
        t,c,s,_=self.exercise([altar(stock=102)]*2,2)
        self.assertEqual(t.inputs,[]);self.assertEqual(c.attentions[-1].code,'penguin_resource')
