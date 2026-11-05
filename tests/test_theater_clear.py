"""Complete Theater victory overlay: dismiss only, never invent completion."""
import copy
from dataclasses import replace
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock
import numpy as np
from PIL import Image, ImageDraw
from abyss_core import Observation, Token
from task_blockers import TaskAttention
from theater_core import classify, plan
from theater_journal import TheaterJournal
from theater_vision import complete_clear_overlay, TheaterVision
from theater_worker import read_observation
import test_theater as helpers


def observation():
    return Observation(1600,900,[helpers.token('CLEAR',800,365),
        Token('1/1',220,10,40,24,source='theater_wave_ocr',score=.99)],visuals={'theater_battle'})


def badge():
    image=Image.new('RGB',(1600,900),'#222222')
    ImageDraw.Draw(image).polygon([(802,45),(865,190),(1080,215),(1080,240),(860,275),
        (802,430),(750,275),(520,240),(520,215),(735,190)],fill='#ffad35')
    return image


class ClearOverlayTests(unittest.TestCase):
    def test_full_shape_counter_and_hud_required(self):
        self.assertTrue(complete_clear_overlay(badge(),observation()))
        for mode in ('word','hud','wave','incomplete_wave','weak_wave','wrong_source','wrong_wave_position','wrong_word_position'):
            o=observation()
            if mode=='word':o.tokens.pop(0)
            elif mode=='hud':o.visuals.clear()
            elif mode=='wave':o.tokens.pop(1)
            elif mode=='incomplete_wave':o.tokens[1]=replace(o.tokens[1],text='1/2')
            elif mode=='weak_wave':o.tokens[1]=replace(o.tokens[1],score=.8)
            elif mode=='wrong_source':o.tokens[1]=replace(o.tokens[1],source='ocr')
            elif mode=='wrong_wave_position':o.tokens[1]=replace(o.tokens[1],x=900)
            else:o.tokens[0]=replace(o.tokens[0],y=600)
            self.assertFalse(complete_clear_overlay(badge(),o),mode)

    def test_single_clear_or_solid_gold_or_partial_badge_never_proves_overlay(self):
        self.assertFalse(complete_clear_overlay(Image.new('RGB',(1600,900),'#222222'),observation()))
        self.assertFalse(complete_clear_overlay(Image.new('RGB',(1600,900),'#ffad35'),observation()))
        image=badge();ImageDraw.Draw(image).rectangle((500,0,730,280),fill='#222222')
        self.assertFalse(complete_clear_overlay(image,observation()))
        image=Image.new('RGB',(1600,900),'#222222');image.paste(badge().crop((500,0,1100,440)),(100,420))
        self.assertFalse(complete_clear_overlay(image,observation()))

    def test_resize_uses_normalized_geometry(self):
        o=observation();o.width,o.height=800,450
        o.tokens=[replace(t,x=t.x/2,y=t.y/2,w=t.w/2,h=t.h/2) for t in o.tokens]
        self.assertTrue(complete_clear_overlay(badge().resize((800,450)),o))

    def test_vision_matches_battle_and_full_badge_before_marking_clear(self):
        image=badge();vision=TheaterVision();tpl=Image.fromarray(vision.templates['battle']).convert('RGB')
        image.paste(tpl,(1300,20));o=observation();o.visuals.clear()
        o=vision.apply(image,o)
        self.assertIn('theater_battle',o.visuals);self.assertIn('theater_clear_overlay',o.visuals)
        self.assertEqual(classify(o).scene,'theater_clear_overlay')
        self.assertEqual(classify(helpers.observation([helpers.token('CLEAR',800,365)],['theater_battle'])).scene,'theater_transition')

    def test_resources_unknown_dialog_and_defeat_still_override_complete_shape(self):
        for text,expected in [('购买门票','theater_blocked'),('装备背包已满','theater_blocked'),
                              ('战斗失败','theater_defeat'),('确认','theater_unknown_dialog')]:
            o=observation();o.visuals.add('theater_clear_overlay');o.tokens.append(helpers.token(text,800,500))
            self.assertEqual(classify(o).scene,expected)

    def test_own_current_playback_chain_required(self):
        o=observation();o.visuals.add('theater_clear_overlay');r=classify(o)
        active=dict(run_id='run',phase='story',playback_evidence='played.png')
        self.assertEqual(plan(r,{'active':active},'run'),'dismiss_clear')
        for a in (None,{**active,'run_id':'old'},{**active,'phase':'await_ticket'},
                  dict(run_id='run',phase='story')):
            with self.assertRaises(TaskAttention):plan(r,{'active':a},'run')

    def test_only_one_dismiss_intent_and_no_fake_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            j=TheaterJournal(folder,'run');l=classify(helpers.listing())
            rec=j.reserve('open',l,'open.png');j.finish(rec,'sent')
            j.state['active'].update(phase='story',playback_evidence='played.png');j.save()
            before=copy.deepcopy(j.state)
            o=observation();o.visuals.add('theater_clear_overlay');r=classify(o)
            rec=j.reserve(plan(r,j.state,'run'),r,'badge.png')
            j.finish(rec,'sent')
            with self.assertRaises(TaskAttention):j.reserve('dismiss_clear',r,'same.png')
            for k in ('attempted','entry_dispatches','completed','last_cleared','active'):
                self.assertEqual(j.state[k],before[k],k)

    def test_external_operator_reservation_also_blocks_worker_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            j=TheaterJournal(folder,'run');l=classify(helpers.listing())
            rec=j.reserve('open',l,'open.png');j.finish(rec,'sent')
            j.state['active'].update(phase='story',playback_evidence='played.png');j.save()
            path=j.clear_operator_dispatch_path();path.parent.mkdir();path.write_text('{}',encoding='utf-8')
            o=observation();o.visuals.add('theater_clear_overlay')
            with self.assertRaises(TaskAttention):j.reserve('dismiss_clear',classify(o),'clear.png')

    def test_clear_ocr_is_enriched_with_separate_brightened_counter_crop(self):
        full=[([[700,330],[900,330],[900,400],[700,400]],'CLEAR',.99)]
        counter=[([[75,30],[230,30],[230,100],[75,100]],'1/1',.99)]
        ocr=Mock(side_effect=[(full,None),(counter,None)])
        o=read_observation(badge(),ocr,123)
        self.assertEqual(ocr.call_count,2)
        wave=[t for t in o.tokens if t.source=='theater_wave_ocr']
        self.assertEqual(len(wave),1);self.assertTrue(o.in_region(wave[0],(.12,0,.18,.06)))
        self.assertEqual(o.captured_at,123)
        ocr=Mock(return_value=([],None));read_observation(badge(),ocr,123);ocr.assert_called_once()

    def test_saved_private_clear_full_image_readonly_replay(self):
        path=Path(__file__).resolve().parents[1]/'.local/theater-clear-20261104/before.png'
        if not path.is_file():self.skipTest('未分发真实剧场私有画面')
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        with Image.open(path) as image:
            o=TheaterVision().apply(image,read_observation(image,ocr,time.monotonic()))
        r=classify(o);self.assertEqual(r.scene,'theater_clear_overlay')
        self.assertEqual(r.target.text,'CLEAR')


    def test_explicit_final_wave_counts_are_not_limited_to_one_wave(self):
        from theater_vision import final_wave_counter
        for text in ('1/1','2/2','3/3','5/5','99/99','2 / 2'):
            self.assertTrue(final_wave_counter(text),text)
            o=observation();o.tokens[1]=replace(o.tokens[1],text=text)
            self.assertTrue(complete_clear_overlay(badge(),o),text)
        for text in ('1/2','2/3','3/5','0/0','01/01','100/100','2/12','X2/2','?/2','2/?','-2/-2','2/2/2'):
            self.assertFalse(final_wave_counter(text),text)
        self.assertFalse(final_wave_counter(None))
        o=observation();o.tokens[1]=replace(o.tokens[1],text='2/2',score=.93)
        self.assertFalse(complete_clear_overlay(badge(),o))
        o=observation();o.tokens[1]=replace(o.tokens[1],text='2/2');o.tokens.append(o.tokens[1])
        self.assertFalse(complete_clear_overlay(badge(),o))
        self.assertFalse(complete_clear_overlay(Image.new('RGB',(1600,900),'black'),o))

    def test_crop_ocr_accepts_only_high_confidence_explicit_final_counter(self):
        full=[([[700,330],[900,330],[900,400],[700,400]],'CLEAR',.99)]
        for text,score,accepted in (('2/2',.99,True),('3/3',.99,True),('1/2',.99,False),
                                    ('2/3',.99,False),('2/2',.93,False),('X2/2',.99,False)):
            counter=[([[75,30],[230,30],[230,100],[75,100]],text,score)]
            o=read_observation(badge(),Mock(side_effect=[(full,None),(counter,None)]),123)
            self.assertEqual(len([t for t in o.tokens if t.source=='theater_wave_ocr']),int(accepted))

    def test_two_wave_clear_dismissal_still_requires_playback_and_never_completes(self):
        o=observation();o.tokens[1]=replace(o.tokens[1],text='2/2');o.visuals.add('theater_clear_overlay')
        r=classify(o);self.assertEqual(r.scene,'theater_clear_overlay')
        with tempfile.TemporaryDirectory() as folder:
            j=TheaterJournal(folder,'run');listing=classify(helpers.listing())
            rec=j.reserve('open',listing,'entry.png');j.finish(rec,'sent')
            with self.assertRaises(TaskAttention):plan(r,j.state,'run')
            j.state['active'].update(phase='story',playback_evidence='play.png');j.save()
            before=copy.deepcopy(j.state)
            rec=j.reserve(plan(r,j.state,'run'),r,'clear-2-2.png');j.finish(rec,'sent')
            with self.assertRaises(TaskAttention):j.reserve('dismiss_clear',r,'again.png')
            for key in ('attempted','completed','entry_dispatches','active','last_cleared','unresolved_entries'):
                self.assertEqual(j.state[key],before[key],key)

    def test_unknown_transition_reports_waiting_not_successful_run(self):
        frame=helpers.observation([helpers.token('CLEAR',800,365)],visuals=['theater_battle'])
        transport,ctl,state=helpers.TheaterWorkerTests().run_frames([frame])
        transport.tap.assert_not_called();self.assertEqual(state['completed'],{})
        self.assertTrue(any(c.kwargs.get('mode')=='waiting_scene' and '零输入' in c.args[0]
                            for c in ctl.status.call_args_list if c.args))

    def test_actual_private_two_wave_clear_is_complete_overlay_not_a_completion(self):
        path=Path(__file__).resolve().parents[1]/'.local/theater-two-wave-20261105/before.png'
        if not path.is_file():self.skipTest('未分发实机2/2终波私有画面')
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        with Image.open(path) as image:
            o=TheaterVision().apply(image,read_observation(image,ocr,time.monotonic()))
        waves=[t for t in o.tokens if t.source=='theater_wave_ocr']
        self.assertEqual(len(waves),1);self.assertEqual(waves[0].text,'2/2');self.assertGreaterEqual(waves[0].score,.94)
        self.assertEqual(classify(o).scene,'theater_clear_overlay');self.assertEqual(classify(o).completed,())
