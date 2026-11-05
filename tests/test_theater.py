"""Offline Theater regressions; synthetic UI, private temp ledgers, fake inputs."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch
import numpy as np
from PIL import Image
from abyss_core import Observation, Token
from assistant_config import validate_run
from assistant_worker import capture_fresh, StopRun
from entry_journal import can_enter
from pc_backend import PcSafetyError, TapNotSent, InputDeliveryError
from pc_message_backend import CaptureUnavailable
from task_blockers import TaskAttention
from theater_core import classify, plan, Episode, Reading, selected_episode
from theater_journal import TheaterJournal
from theater_vision import TheaterVision
from theater_worker import read_observation


def token(text, x, y, score=.99, w=100, h=28):
    return Token(text, x-w/2, y-h/2, w, h, score=score)


def observation(tokens=(), visuals=()):
    return Observation(1600, 900, list(tokens), visuals=set(visuals))


def listing(number=7, extra=()):
    return observation([token('月光剧场', 180, 70), token('剧目：没落的大地', 980, 165),
                        token(f'第{number}集', 1100, 335), token('进行观览', 1400, 805), *extra])


def ticket(cost=1, extra=()):
    return observation([token('使用剧场门票', 800, 280), token(f'是否使用剧场门票{cost}张进行观览？', 800, 400),
                        token('取消', 600, 610), token('确认', 1000, 610), *extra])


def guide():
    return observation([token('观览指南', 800, 270), token('月光剧场的故事无法跳过。', 800, 370),
                        token('是否要开始观览？', 800, 430), token('确认', 1000, 610)])


class TheaterRecognitionTests(unittest.TestCase):
    def test_list_identity_and_button_not_generic_title(self):
        r=classify(listing());self.assertEqual(r.scene,'theater_list')
        self.assertEqual(r.episode,Episode('没落的大地',7));self.assertEqual(r.target.center,(1400,805))
        for index in (0,1,2,3):
            o=listing();o.tokens.pop(index);r=classify(o)
            if index in (1,2):self.assertIsNone(r.episode)
            else:self.assertNotEqual(r.scene,'theater_list')
    def test_plain_large_heading_supported_but_ambiguous_or_small_not_guessed(self):
        o=listing();o.tokens[1]=token('没落的大地',980,165)
        self.assertEqual(selected_episode(o),Episode('没落的大地',7))
        o.tokens.append(token('零之缺陷都市',980,220));self.assertIsNone(selected_episode(o))
        o=listing();o.tokens[1]=token('没落的大地',980,165,h=12)
        self.assertIsNone(selected_episode(o))
    def test_multiple_or_low_confidence_episode_is_unknown(self):
        o=listing(extra=[token('第8集',1200,400)]);self.assertIsNone(selected_episode(o))
        o=listing();o.tokens[2]=token('第7集',1100,335,score=.4)
        self.assertIsNone(selected_episode(o))
    def test_ticket_requires_explicit_one_cost_unique_confirm_geometry_and_confidence(self):
        self.assertEqual(classify(ticket()).scene,'theater_ticket')
        for cost in (0,2,10):self.assertEqual(classify(ticket(cost)).scene,'theater_unknown_dialog')
        for extra in ([token('确认',1000,620)], [token('确认',800,50)], [token('购买门票',800,500,score=.2)]):
            self.assertNotEqual(classify(ticket(extra=extra)).scene,'theater_ticket')
        o=ticket();o.tokens[1]=token('是否使用剧场门票1张进行观览？',800,400,score=.4)
        self.assertEqual(classify(o).scene,'theater_unknown_dialog')
        o=ticket();o.tokens[-1]=token('确认',1000,610,score=.4)
        self.assertEqual(classify(o).scene,'theater_unknown_dialog')
    def test_guide_must_have_complete_caption_before_background_list(self):
        o=guide();o.tokens.extend(listing().tokens)
        self.assertEqual(classify(o).scene,'theater_guide')
        for i in (0,1,2):
            o=guide();o.tokens.pop(i)
            self.assertEqual(classify(o).scene,'theater_unknown_dialog')
    def test_unknown_does_not_default_to_story_and_battle_wins_over_story(self):
        self.assertEqual(classify(observation([token('陌生提示',800,400)])).scene,'theater_unknown')
        self.assertEqual(classify(observation(visuals=['theater_story'])).scene,'theater_story')
        self.assertEqual(classify(observation(visuals=['theater_story','theater_battle'])).scene,'theater_battle')
        self.assertEqual(classify(observation([token('确认',800,600)],['theater_story'])).scene,'theater_unknown_dialog')
    def test_clear_alone_never_authorizes_a_tap(self):
        o=observation([token('CLEAR',800,400)],['theater_story','theater_battle'])
        self.assertEqual(classify(o).scene,'theater_transition')
        o.tokens.append(token('点击继续',800,790));self.assertEqual(classify(o).scene,'theater_victory')
    def test_resources_capacity_and_defeat_override_story_and_confirmation(self):
        for text,scene in [('购买门票','theater_blocked'),('复活','theater_blocked'),
                           ('装备背包已满','theater_blocked'),('战斗失败','theater_defeat')]:
            o=ticket(extra=[token(text,800,500,score=.2)]);o.visuals.add('theater_story')
            self.assertEqual(classify(o).scene,scene)
    def test_completed_marker_and_next_button_are_independent_of_victory(self):
        o=listing(extra=[token('已观览',1200,450),token('下一集',1390,710)])
        r=classify(o);self.assertEqual(r.scene,'theater_next');self.assertEqual(r.completed,(7,))
        self.assertEqual(r.target.center,(1390,710))
    def test_completed_on_screen_is_blocked_even_without_local_attempt(self):
        r=classify(listing(extra=[token('已观览',1200,450)]))
        with self.assertRaises(TaskAttention):plan(r,{'attempted':{},'completed':{},'active':None},'new')
    def test_locked_selection_and_extra_ticket_fees_never_enter(self):
        self.assertEqual(classify(listing(extra=[token('未解锁',1200,450)])).scene,'theater_blocked')
        o=ticket();o.tokens[1]=token('是否使用剧场门票1张进行观览并消耗100金币？',800,400)
        self.assertEqual(classify(o).scene,'theater_unknown_dialog')
        o=observation([token('好的',800,600)],['theater_story'])
        self.assertEqual(classify(o).scene,'theater_unknown_dialog')
    def test_ocr_normalization_maps_back_to_native_coordinates_and_keeps_weak_risks(self):
        box=[[1350,790],[1450,790],[1450,820],[1350,820]]
        o=read_observation(Image.new('RGB',(800,450)),Mock(return_value=([(box,'购买',.2)],None)),10)
        self.assertEqual(o.tokens[0].center,(700,402.5));self.assertEqual(o.tokens[0].score,.2)
    def test_task_validation_pc_only_no_history_replacement(self):
        settings={'task':'theater','pc_input':'messages'}
        with self.assertRaisesRegex(ValueError,'MuMu'):validate_run(settings,{'client':'mumu'})
        with patch('assistant_portable.registered_root',return_value=None):
            validate_run(settings,{'client':'pc'})
    def test_template_matching_location_and_resizing_with_negative_controls(self):
        vision=TheaterVision()
        for name,tpl in vision.templates.items():
            canvas=np.full((900,1600),30,np.uint8);h,w=tpl.shape
            canvas[20:20+h,1300:1300+w]=tpl
            im=Image.fromarray(canvas).convert('RGB')
            self.assertIn('theater_'+name,vision.apply(im,observation()).visuals)
            self.assertIn('theater_'+name,vision.apply(im.resize((800,450)),observation()).visuals)
            canvas[:]=30;canvas[300:300+h,400:400+w]=tpl
            self.assertNotIn('theater_'+name,vision.apply(Image.fromarray(canvas).convert('RGB'),observation()).visuals)
        self.assertEqual(vision.apply(Image.new('RGB',(1600,900),'#222222'),observation()).visuals,set())


class TheaterJournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.profile=Path(self.tmp.name)
        self.mainline=self.profile/'state.json';self.mainline.write_text('{"keep":"mainline"}',encoding='utf-8')
        self.j=TheaterJournal(self.profile,'run1');self.r=classify(listing())
    def tearDown(self):self.tmp.cleanup()
    def open(self):
        record=self.j.reserve('open',self.r,'evidence/open.png');self.j.finish(record,'sent');return record
    def start(self):
        self.open();r=classify(ticket());self.j.finish(self.j.reserve('ticket',r,'evidence/ticket.png'),'sent')
        r=classify(guide());self.j.finish(self.j.reserve('guide',r,'evidence/guide.png'),'sent')
    def test_intent_saved_before_send_and_unknown_result_stays_blocked(self):
        r=self.j.reserve('open',self.r,'evidence/open.png')
        saved=json.loads(self.j.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['entry_dispatches'][self.r.episode.key][0]['status'],'reserved')
        self.assertFalse(can_enter(saved,self.r.episode.key))
        reopened=TheaterJournal(self.profile,'run2')
        self.assertEqual(reopened.state['unresolved_entries'][0]['entry']['key'],self.r.episode.key)
        self.assertFalse(can_enter(reopened.state,self.r.episode.key));self.assertIsNone(reopened.state['active'])
        self.assertEqual(self.mainline.read_text(),'{"keep":"mainline"}')
    def test_only_proven_not_sent_allows_new_open_and_keeps_attempt(self):
        rec=self.j.reserve('open',self.r,'open.png');before=copy.deepcopy(self.j.state['attempted'])
        self.j.finish(rec,'not_sent','TapNotSent: before press')
        self.assertTrue(can_enter(self.j.state,self.r.episode.key));self.assertEqual(self.j.state['attempted'],before)
        self.assertEqual(plan(self.r,self.j.state,'run1'),'open')
    def test_ticket_and_guide_are_not_completed_or_double_sent(self):
        with self.assertRaises(TaskAttention):plan(classify(ticket()),self.j.state,'run1')
        self.open();self.assertEqual(plan(classify(ticket()),self.j.state,'run1'),'ticket')
        rec=self.j.reserve('ticket',classify(ticket()),'ticket.png');self.j.finish(rec,'sent')
        self.assertEqual(self.j.state['completed'],{})
        with self.assertRaises(TaskAttention):plan(classify(ticket()),self.j.state,'run1')
        self.assertEqual(plan(classify(guide()),self.j.state,'run1'),'guide')
    def test_cancelled_ticket_can_continue_once_but_uncertain_ticket_cannot(self):
        self.open();r=classify(ticket());rec=self.j.reserve('ticket',r,'ticket.png')
        with self.assertRaises(TaskAttention):self.j.reserve('ticket',r,'again.png')
        self.j.finish(rec,'not_sent','before press');new=self.j.reserve('ticket',r,'fresh.png')
        self.j.finish(new,'sent')
        with self.assertRaises(TaskAttention):self.j.reserve('ticket',r,'again.png')
    def test_completion_needs_owned_playback_same_production_and_explicit_completed_status(self):
        self.start();before=copy.deepcopy(self.j.state)
        self.assertFalse(self.j.observe(classify(listing(8)),'new-list.png'))
        self.assertEqual(self.j.state,before)
        self.j.observe(classify(observation(visuals=['theater_story'])),'play.png')
        self.assertFalse(self.j.observe(classify(listing(8)),'new-list.png'))
        result=classify(listing(8,extra=[token('第7集 已观览',300,500)]))
        self.assertTrue(self.j.observe(result,'independent-list.png'))
        self.assertIn(self.r.episode.key,self.j.state['completed']);self.assertIsNone(self.j.state['active'])
        self.assertEqual(self.j.state['last_cleared']['completion_evidence'],'independent-list.png')
    def test_same_episode_number_different_productions_do_not_collide(self):
        self.assertNotEqual(Episode('没落的大地',7).key,Episode('零之缺陷都市',7).key)
    def test_old_active_is_archived_never_backfilled_from_new_run_result(self):
        self.start();self.j.observe(classify(observation(visuals=['theater_story'])),'play.png')
        new=TheaterJournal(self.profile,'run2');before=copy.deepcopy(new.state['attempted'])
        self.assertFalse(new.observe(classify(listing(extra=[token('已观览',1200,450)])),'result.png'))
        self.assertEqual(new.state['attempted'],before);self.assertEqual(new.state['completed'],{})
        self.assertEqual(len(new.state['unresolved_entries']),1)
    def test_missing_or_corrupt_registered_ledger_does_not_reinitialize(self):
        self.j.path.unlink()
        with self.assertRaises(RuntimeError):TheaterJournal(self.profile,'run2')
        self.assertFalse(self.j.path.exists())
    def test_deleting_entire_mode_directory_cannot_bypass_registration(self):
        import shutil
        self.open();shutil.rmtree(self.j.root)
        with self.assertRaises(RuntimeError):TheaterJournal(self.profile,'run2')
        self.assertFalse(self.j.path.exists())
    def test_critical_write_failure_prevents_reservation_return(self):
        with patch('theater_journal.durable_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.j.reserve('open',self.r,'open.png')
    def test_evidence_saved_with_hash_before_intent(self):
        im=Image.new('RGB',(800,450),'#445566');snap=SimpleNamespace(image=im,captured_at=123)
        proof=self.j.evidence(snap,listing(),self.r)
        meta=json.loads((self.j.root/Path(proof).with_suffix('.json')).read_text(encoding='utf-8'))
        self.assertEqual(meta['run_id'],'run1');self.assertEqual(meta['captured_at'],123)
        self.assertEqual(len(meta['image_sha256']),64)


class TheaterCaptureTests(unittest.TestCase):
    def test_long_fade_waits_without_input_and_recovers(self):
        capture=Mock(side_effect=[CaptureUnavailable('black'),CaptureUnavailable('black'),'fresh'])
        clock=Mock(side_effect=[0,20]);ctl=Mock()
        self.assertEqual(capture_fresh(capture,ctl,clock,blank_budget=300),'fresh')
        ctl.attention.assert_not_called();self.assertEqual(ctl.sleep.call_count,2)
    def test_blank_budget_requires_explicit_attention_resume(self):
        capture=Mock(side_effect=[CaptureUnavailable('black')]*2+['fresh']);ctl=Mock()
        self.assertEqual(capture_fresh(capture,ctl,Mock(side_effect=[0,301]),blank_budget=300),'fresh')
        ctl.attention.assert_called_once()
    def test_geometry_exception_is_never_retried_as_black_frame(self):
        capture=Mock(side_effect=PcSafetyError('geometry'));ctl=Mock()
        with self.assertRaises(PcSafetyError):capture_fresh(capture,ctl,blank_budget=300)
        capture.assert_called_once();ctl.sleep.assert_not_called()


class TheaterWorkerTests(unittest.TestCase):
    def run_frames(self, frames, tap_error=None, save_error=False, processing_seconds=None):
        from theater_worker import run
        with tempfile.TemporaryDirectory() as d:
            ctl=Mock();ctl.sleep.return_value=None
            transport=Mock();transport.ensure.return_value='bound-window'
            now=[100.0]
            clock=time.monotonic if processing_seconds is None else lambda:now[0]
            capture_items=[SimpleNamespace(image=Image.new('RGB',(1600,900),'#333333'),captured_at=clock()) for _ in frames]
            transport.capture.side_effect=[*capture_items,StopRun()]
            if tap_error:transport.tap.side_effect=tap_error
            transport.input_times=[]
            readings=iter(frames)
            def read(*args):
                if processing_seconds is not None:now[0]+=processing_seconds
                return next(readings)
            if processing_seconds is not None:
                def click(*args,**kwargs):
                    transport.input_times.append(now[0])
                    if tap_error:raise tap_error
                    now[0]+=kwargs.get('press_seconds',.07)
                transport.tap.side_effect=click
                def sleep(seconds):now[0]+=seconds
                ctl.sleep.side_effect=sleep
            ctl.attention.side_effect=StopRun()
            request={'settings':{'task':'theater','observe':False},'target':{'client':'pc'},'run_id':'test'}
            vision=Mock();vision.apply.side_effect=lambda image,o:o
            with patch('assistant_config.validate_run',return_value=(Path(d),{})),patch('assistant_transport.UnifiedTransport',return_value=transport),patch('rapidocr_onnxruntime.RapidOCR'),patch('theater_worker.TheaterVision',return_value=vision),patch('theater_worker.read_observation',side_effect=read),patch('assistant_worker.wait_for_input',return_value=False):
                writes=patch('theater_journal.TheaterJournal.reserve',side_effect=OSError('disk full')) if save_error else patch('theater_worker.time.monotonic',side_effect=clock)
                with writes:
                    with self.assertRaises((StopRun,OSError)):run(request,ctl)
            path=Path(d)/'theater'/'state.json'
            return transport,ctl,json.loads(path.read_text(encoding='utf-8'))
    def test_unknown_and_battle_never_click(self):
        transport,_,s=self.run_frames([observation(),observation(visuals=['theater_battle'])])
        transport.tap.assert_not_called();self.assertEqual(s['attempted'],{})
    def test_story_uses_new_ocr_every_time_and_stops_on_changed_target(self):
        transport,_,s=self.run_frames([observation(visuals=['theater_story']),ticket()])
        self.assertEqual(transport.tap.call_count,1);self.assertEqual(s['completed'],{})
    def test_fast_recognition_spacing_is_quarter_second_with_ten_ms_story_press(self):
        transport,ctl,_=self.run_frames([observation(visuals=['theater_story']) for _ in range(3)],processing_seconds=.001)
        self.assertEqual(transport.tap.call_count,3)
        times=transport.input_times
        for a,b in zip(times,times[1:]):self.assertAlmostEqual(b-a,.25)
        self.assertTrue(all(c.kwargs=={'press_seconds':.01} for c in transport.tap.call_args_list))
        self.assertTrue(all(0<c.args[0]<=.25 for c in ctl.sleep.call_args_list))
    def test_slow_recognition_adds_no_wait_or_catch_up_clicks(self):
        transport,ctl,_=self.run_frames([observation(visuals=['theater_story']) for _ in range(3)],processing_seconds=.4)
        self.assertEqual(transport.tap.call_count,3);ctl.sleep.assert_not_called()
        for a,b in zip(transport.input_times,transport.input_times[1:]):self.assertAlmostEqual(b-a,.41)
    def test_navigation_and_ticket_keep_normal_press_with_quarter_second_cycles(self):
        transport,ctl,_=self.run_frames([listing(),ticket(),guide()],processing_seconds=.001)
        self.assertEqual(transport.tap.call_count,3)
        self.assertTrue(all(c.kwargs=={} for c in transport.tap.call_args_list))
        for a,b in zip(transport.input_times,transport.input_times[1:]):self.assertAlmostEqual(b-a,.25)
    def test_partial_load_waits_then_first_verified_control_acts_without_full_page_wait(self):
        transport,ctl,_=self.run_frames([observation(),listing()],processing_seconds=.001)
        self.assertEqual(transport.tap.call_count,1)
        self.assertAlmostEqual(transport.input_times[0],100.251)
        self.assertEqual(transport.capture.call_count,3)
        ctl.attention.assert_not_called()
    def test_unknown_and_battle_poll_every_quarter_second_without_input(self):
        transport,ctl,_=self.run_frames([observation(),observation(visuals=['theater_battle'])],processing_seconds=.001)
        transport.tap.assert_not_called()
        self.assertEqual(ctl.sleep.call_count,2)
        for call in ctl.sleep.call_args_list:self.assertAlmostEqual(call.args[0],.249)
    def test_complete_flow_is_one_ticket_guide_and_story_no_fake_completion(self):
        transport,_,s=self.run_frames([listing(),ticket(),guide(),observation(visuals=['theater_story'])])
        self.assertEqual(transport.tap.call_count,4);self.assertEqual(s['completed'],{})
        self.assertEqual(len([a for a in s['actions'] if a['kind']=='ticket']),1)
    def test_completed_episode_allows_verified_next_episode_with_independent_entry(self):
        result=listing(8,extra=[token('第7集 已观览',300,500)])
        transport,ctl,s=self.run_frames([listing(),ticket(),guide(),
            observation(visuals=['theater_story']),result,ticket(),guide()])
        self.assertEqual(len(s['attempted']),2);self.assertEqual(len(s['completed']),1)
        self.assertEqual(s['active']['number'],8)
        self.assertEqual(len([a for a in s['actions'] if a['kind']=='ticket']),2)
        self.assertTrue(any(c.kwargs.get('wins')==1 for c in ctl.status.call_args_list))
    def test_paid_scene_staying_visible_is_not_confirmed_twice(self):
        transport,_,s=self.run_frames([listing(),ticket(),ticket(),ticket()])
        self.assertEqual(transport.tap.call_count,2)
        self.assertEqual(len([a for a in s['actions'] if a['kind']=='ticket']),1)
    def test_waiting_on_clear_does_not_count_success(self):
        transport,_,s=self.run_frames([observation([token('CLEAR',800,400)],['theater_battle'])])
        transport.tap.assert_not_called();self.assertEqual(s['completed'],{})
    def test_write_failure_sends_no_input(self):
        transport,_,_=self.run_frames([listing()],save_error=True)
        transport.tap.assert_not_called()
    def test_not_sent_distinct_from_delivery_unknown(self):
        for error,status in [(TapNotSent('before down'),'not_sent'),(InputDeliveryError('unknown'),'reserved')]:
            with self.subTest(status=status):
                transport,ctl,s=self.run_frames([listing()],tap_error=error)
                self.assertEqual(transport.tap.call_count,1);ctl.attention.assert_called_once()
                record=next(iter(s['entry_dispatches'].values()))[0]
                self.assertEqual(record['status'],status)


if __name__=='__main__':unittest.main()
