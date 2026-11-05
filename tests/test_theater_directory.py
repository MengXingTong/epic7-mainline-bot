"""Observed directory layout and explicit geometry-resume regressions, no live input."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
from abyss_core import Observation, Token
from assistant_config import read_json
from assistant_worker import StopRun
from entry_journal import can_enter
from pc_backend import PcSafetyError, WindowSnapshot
from pc_message_backend import CaptureUnavailable
from task_blockers import TaskAttention
from theater_core import Episode, classify, plan
from theater_journal import TheaterJournal
from theater_vision import TheaterVision
import test_theater as theater_tests
from test_theater import token, observation, listing, ticket, guide


def directory(selected=8, completed=(5, 6, 7), locked=(9, 10), stock=11, checks=True):
    im=Image.new('RGB',(1600,900),'#253028');draw=ImageDraw.Draw(im)
    tokens=[token('月光剧场',150,40),token('目录',1285,135),
            token('第1季',1480,130),token('第2季',1480,240),
            token('没落',140,190,w=150,h=90),token('大地',285,245,w=210,h=135),
            token(f'第{selected}集·贤明的协调',180,620,w=250),
            token(f'1/{stock}',900,830,w=65),token('进行观览',1040,830,w=120)]
    for number in range(5,11):
        cy=225+(number-5)*110
        tokens.append(token(f'第{number}集',1228,cy,w=70))
        if number in completed:
            tokens.append(token('完成',1255,cy+36,w=50))
            if checks:draw.line([(1186,cy+27),(1193,cy+34),(1210,cy+17)],fill='#5fd714',width=4)
        elif number in locked:tokens.append(token('无法观览',1265,cy+36,w=90))
        else:tokens.append(token('6天后可观览',1280,cy+36,w=130))
        if number==selected:
            draw.rounded_rectangle((1180,cy-37,1390,cy+53),radius=12,outline='#ebe16e',width=3)
    draw.line((1405,88,1405,172),fill='#239dff',width=5)
    o=Observation(1600,900,tokens)
    return im,o


class DirectoryTests(unittest.TestCase):
    def reading(self,**kwargs):
        im,o=directory(**kwargs);return classify(TheaterVision().apply(im,o)),o
    def test_current_ticket_episode_not_blocked_by_later_locked_rows(self):
        r,o=self.reading()
        self.assertEqual(r.scene,'theater_list');self.assertEqual(r.episode,Episode('没落大地',8,1))
        self.assertEqual((r.ticket_cost,r.ticket_stock),(1,11));self.assertEqual(r.completed,(5,6,7))
        self.assertEqual(plan(r,{'attempted':{},'completed':{},'active':None},'run'),'open')
    def test_selected_locked_episode_still_blocks(self):
        r,_=self.reading(selected=9)
        self.assertEqual(r.scene,'theater_blocked')
    def test_zero_or_ambiguous_stock_blocks(self):
        r,_=self.reading(stock=0);self.assertEqual(r.scene,'theater_blocked')
        im,o=directory();o.tokens.append(token('1/999',900,850,w=65))
        self.assertEqual(classify(TheaterVision().apply(im,o)).scene,'theater_blocked')
    def test_detail_and_gold_outline_must_agree(self):
        im,o=directory();o.tokens[6]=token('第9集·别的故事',180,620,w=250)
        r=classify(TheaterVision().apply(im,o));self.assertIsNone(r.episode)
        with self.assertRaises(TaskAttention):plan(r,{'attempted':{},'completed':{},'active':None},'run')
    def test_season_and_production_required_no_guess_from_currency_or_cast(self):
        for remove in ('season','logo'):
            im,o=directory()
            if remove=='season':ImageDraw.Draw(im).rectangle((1400,80,1410,180),fill='#253028')
            else:o.tokens=[t for t in o.tokens if t.text not in ('没落','大地')]
            self.assertIsNone(classify(TheaterVision().apply(im,o)).episode)
    def test_missing_tick_does_not_turn_complete_episode_into_new_entry(self):
        r,_=self.reading(selected=8,completed=(5,6,7,8),locked=(10,),checks=False)
        self.assertEqual(r.scene,'theater_blocked')
    def test_green_rectangle_is_not_a_completion_tick(self):
        im,o=directory(completed=(5,6,7,8),locked=(10,))
        cy=225+3*110
        ImageDraw.Draw(im).rectangle((1182,cy+14,1214,cy+36),fill='#5fd714')
        o=TheaterVision().apply(im,o)
        self.assertNotIn('theater_complete:8',o.visuals)
        self.assertEqual(classify(o).scene,'theater_blocked')
    def test_ambiguous_selected_season_does_not_invent_episode_key(self):
        im,o=directory();ImageDraw.Draw(im).line((1405,198,1405,282),fill='#239dff',width=5)
        self.assertIsNone(classify(TheaterVision().apply(im,o)).episode)
    def test_native_resize_keeps_selected_episode_and_ticket_geometry(self):
        for width,height in ((800,450),(1280,720)):
            im,o=directory();sx,sy=width/1600,height/900
            o=Observation(width,height,[Token(t.text,t.x*sx,t.y*sy,t.w*sx,t.h*sy,score=t.score) for t in o.tokens])
            r=classify(TheaterVision().apply(im.resize((width,height)),o))
            self.assertEqual(r.episode,Episode('没落大地',8,1));self.assertEqual(r.ticket_stock,11)
    def test_small_native_outline_still_requires_every_side(self):
        for side in ((1175,513,1395,526), (1175,600,1395,613),
                     (1175,513,1188,613), (1383,513,1395,613)):
            im,o=directory()
            ImageDraw.Draw(im).rectangle(side,fill='#253028')
            width,height=816,459;sx,sy=width/1600,height/900
            o=Observation(width,height,[Token(t.text,t.x*sx,t.y*sy,t.w*sx,t.h*sy,score=t.score) for t in o.tokens])
            r=classify(TheaterVision().apply(im.resize((width,height)),o))
            self.assertNotIn('theater_selected:8',o.visuals)
            self.assertIsNone(r.episode)

    def test_private_small_native_directory_requires_same_frame_identity_and_cost(self):
        path=Path(__file__).resolve().parents[1]/'.local/theater-stall-20261105/20261105T133412.png'
        if not path.is_file():self.skipTest('未分发816x459剧场私有画面')
        from rapidocr_onnxruntime import RapidOCR
        from theater_worker import read_observation
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        with Image.open(path) as im:
            o=TheaterVision().apply(im,read_observation(im,ocr,time.monotonic()))
        r=classify(o)
        self.assertEqual(r.scene,'theater_list')
        self.assertEqual(r.episode,Episode('没落大地',2,2))
        self.assertEqual((r.ticket_cost,r.ticket_stock),(1,12))
        # Clipped prior row does not become independent completion evidence.
        self.assertNotIn(1,r.completed)
        state={'active':None,'attempted':{},'completed':{}}
        self.assertEqual(plan(r,state,'run'),'open')
        state['attempted'][r.episode.key]={'outcome':'unknown'}
        with self.assertRaises(TaskAttention):plan(r,state,'run')
        o.tokens.append(token('确认',800*.51,500*.51))
        self.assertEqual(classify(o).scene,'theater_unknown_dialog')

    def test_directory_worker_completes_then_selects_and_enters_next_once(self):
        def frame(**kwargs):
            im,o=directory(**kwargs);return TheaterVision().apply(im,o)
        frames=[frame(),ticket(),guide(),observation(visuals=['theater_story']),
                frame(completed=(5,6,7,8),locked=(10,)),
                frame(selected=9,completed=(5,6,7,8),locked=(10,),stock=10),ticket(),guide()]
        transport,ctl,state=theater_tests.TheaterWorkerTests().run_frames(frames)
        self.assertEqual(len(state['completed']),1);self.assertEqual(len(state['attempted']),2)
        self.assertEqual(state['active']['number'],9);self.assertEqual(state['active']['season'],1)
        self.assertEqual(len([r for r in state['actions'] if r['kind']=='select']),1)
        self.assertEqual(len([r for r in state['actions'] if r['kind']=='ticket']),2)
    def test_completed_current_selects_exact_next_unlocked_row(self):
        r,_=self.reading(completed=(5,6,7,8),locked=(10,))
        self.assertEqual(r.scene,'theater_select_episode');self.assertEqual(r.next_episode,Episode('没落大地',9,1))
        self.assertIn(8,r.completed)
        ledger={'attempted':{},'completed':{},'active':None}
        self.assertEqual(plan(r,ledger,'run'),'select')
        ledger['attempted'][r.next_episode.key]={'outcome':'unknown'}
        with self.assertRaises(TaskAttention):plan(r,ledger,'run')
    def test_next_locked_or_missing_never_guessed(self):
        r,_=self.reading(completed=(5,6,7,8),locked=(9,10))
        self.assertEqual(r.scene,'theater_empty')
    def test_season_keys_distinct_but_legacy_attempt_still_blocks(self):
        r,_=self.reading()
        self.assertNotEqual(r.episode.key,Episode('没落大地',8,2).key)
        ledger={'attempted':{'没落大地|episode:8':{'outcome':'unknown'}},'completed':{},'active':None}
        with self.assertRaises(TaskAttention):plan(r,ledger,'run')
    def test_modal_and_purchase_still_override_directory(self):
        for text,scene in [('确认','theater_unknown_dialog'),('购买门票','theater_blocked')]:
            im,o=directory();o.tokens.append(token(text,800,500))
            self.assertEqual(classify(TheaterVision().apply(im,o)).scene,scene)
    def test_actual_saved_directory_with_eleven_tickets(self):
        path=Path(__file__).resolve().parents[1]/'.local/theater-fix-20261104/directory-before.png'
        if not path.is_file():self.skipTest('未分发真实剧场私有画面')
        meta=read_json(path.with_suffix('.json'))
        o=Observation(meta['width'],meta['height'],[Token(**t) for t in meta['tokens']])
        with Image.open(path) as im:r=classify(TheaterVision().apply(im,o))
        self.assertEqual(r.scene,'theater_list');self.assertEqual(r.episode,Episode('没落大地',8,1))
        self.assertEqual((r.ticket_cost,r.ticket_stock),(1,11));self.assertEqual(r.completed,(5,6,7))
    def test_completion_requires_same_season_and_own_playback(self):
        with tempfile.TemporaryDirectory() as folder:
            j=TheaterJournal(folder,'run');r,_=self.reading()
            record=j.reserve('open',r,'before.png');j.finish(record,'sent')
            j.state['active'].update(phase='story',playback_evidence='play.png');j.save()
            result,_=self.reading(completed=(5,6,7,8),locked=(10,))
            from dataclasses import replace
            wrong=replace(result,episode=Episode('没落大地',8,2))
            self.assertFalse(j.observe(wrong,'wrong-season.png'))
            self.assertTrue(j.observe(result,'independent-complete.png'))
            self.assertEqual(j.state['last_cleared']['season'],1)


class GeometryResumeTests(unittest.TestCase):
    def run_sequence(self,*,blocked_first=False,replace_process=False,blank_first=False,uncertain_entry=False,resize=False):
        from theater_worker import run
        with tempfile.TemporaryDirectory() as folder:
            first=WindowSnapshot(1,2,'game.exe',3,100,100,1600,900)
            moved=WindowSnapshot(1,2,'game.exe',3,260,180,1280 if resize else 1600,720 if resize else 900)
            ctl=Mock();transport=Mock();current=[first];ensure_calls=[0];capture_calls=[0];resumed=[False]
            def ensure():
                ensure_calls[0]+=1
                if not blocked_first and ensure_calls[0]==2:current[0]=moved
                if resumed[0] and replace_process:raise PcSafetyError('process replaced')
                return current[0]
            transport.ensure.side_effect=ensure
            frames=[observation([token('购买门票',800,500)]),listing()] if blocked_first else [listing()]
            def capture():
                capture_calls[0]+=1
                if blank_first and capture_calls[0]==1:
                    current[0]=moved;raise CaptureUnavailable('black')
                if not frames:raise StopRun()
                transport.frame=SimpleNamespace(image=Image.new('RGB',(current[0].width,current[0].height)),binding=current[0],captured_at=time.monotonic())
                return transport.frame
            transport.capture.side_effect=capture
            def read(image,*args):
                o=frames.pop(0);sx,sy=image.width/o.width,image.height/o.height
                return Observation(image.width,image.height,[Token(t.text,t.x*sx,t.y*sy,t.w*sx,t.h*sy,score=t.score) for t in o.tokens])
            def attention(exc):
                if resumed[0]:raise StopRun()
                resumed[0]=True;current[0]=moved
            ctl.attention.side_effect=attention
            if uncertain_entry:
                # No initial move: fail only after the durable open intent.
                transport.ensure.side_effect=lambda:current[0]
                def tap(snap,target,**kwargs):current[0]=moved;raise PcSafetyError('geometry after intent')
                transport.tap.side_effect=tap
                frames.append(listing())
            request={'settings':{'task':'theater','observe':False},'target':{'client':'pc'},'run_id':'run'}
            vision=Mock();vision.apply.side_effect=lambda im,o:o
            with patch('assistant_config.validate_run',return_value=(Path(folder),{})),patch('assistant_transport.UnifiedTransport',return_value=transport),patch('rapidocr_onnxruntime.RapidOCR'),patch('theater_worker.TheaterVision',return_value=vision),patch('theater_worker.read_observation',side_effect=read),patch('assistant_worker.wait_for_input',return_value=False):
                with self.assertRaises((StopRun,PcSafetyError)):run(request,ctl)
            state=json.loads((Path(folder)/'theater/state.json').read_text(encoding='utf-8'))
            return transport,ctl,state
    def test_move_waits_for_explicit_resume_then_uses_new_frame(self):
        transport,ctl,state=self.run_sequence()
        ctl.attention.assert_called_once();self.assertEqual(transport.capture.call_count,2)
        transport.tap.assert_called_once();snap=transport.tap.call_args.args[0]
        self.assertEqual(snap.binding.x,260);self.assertEqual(len(state['attempted']),1)
    def test_resource_attention_then_manual_move_needs_only_one_resume(self):
        transport,ctl,state=self.run_sequence(blocked_first=True)
        ctl.attention.assert_called_once();transport.tap.assert_called_once()
        self.assertEqual(transport.tap.call_args.args[0].binding.x,260)
    def test_resize_resume_uses_new_native_frame_and_coordinates(self):
        transport,ctl,_=self.run_sequence(resize=True)
        ctl.attention.assert_called_once();transport.tap.assert_called_once()
        snap,target=transport.tap.call_args.args
        self.assertEqual(snap.image.size,(1280,720))
        self.assertAlmostEqual(target.center[0],1120);self.assertAlmostEqual(target.center[1],644)
    def test_replaced_process_after_resume_still_stops(self):
        transport,ctl,state=self.run_sequence(replace_process=True)
        ctl.attention.assert_called_once();transport.tap.assert_not_called()
        self.assertEqual(state['attempted'],{})
    def test_geometry_during_black_wait_never_rebinds_silently(self):
        # blank capture starts at the old geometry; movement occurs while the
        # capture helper is waiting. The attention must precede any valid tap.
        transport,ctl,_=self.run_sequence(blank_first=True,blocked_first=True)
        self.assertGreaterEqual(ctl.attention.call_count,1)
        self.assertEqual(ctl.attention.call_args_list[0].args[0].code,'client_input')
    def test_geometry_after_intent_keeps_unknown_dispatch_and_never_reopens(self):
        transport,ctl,state=self.run_sequence(uncertain_entry=True)
        transport.tap.assert_called_once();self.assertEqual(len(state['attempted']),1)
        self.assertFalse(can_enter(state,next(iter(state['attempted']))))
        self.assertEqual(next(iter(state['entry_dispatches'].values()))[0]['status'],'reserved')


if __name__=='__main__':unittest.main()
