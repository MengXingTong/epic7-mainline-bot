"""Reported startup/entry cancellation regressions; no real game input."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

import runner
from assistant_transport import UnifiedTransport,FrameSnapshot
from client_viewport import Viewport,pc_viewport
from entry_journal import can_enter,reserve_entry,finish_dispatch
from pc_backend import PcBackend,InputBusy,InputDeliveryError,PcSafetyError,TapNotSent
from test_pc_backend import FakeApi
from test_map_layout import fake_runner,frame
from task_blockers import TaskAttention


class EntryJournalTests(unittest.TestCase):
    def test_cancelled_reservation_keeps_original_and_all_dispatches(self):
        ledger={'attempted':{},'completed':{}}
        original={'key':'stage','start_epoch':100,'evidence':'keep.png'}
        first=reserve_entry(ledger,'stage',original)
        self.assertFalse(can_enter(ledger,'stage'))
        finish_dispatch(first,'not_sent','zero button down')
        self.assertTrue(can_enter(ledger,'stage'))
        second=reserve_entry(ledger,'stage',{**original,'start_epoch':200})
        self.assertFalse(can_enter(ledger,'stage'))
        finish_dispatch(second,'sent')
        self.assertFalse(can_enter(ledger,'stage'))
        self.assertEqual(ledger['attempted']['stage'],original)
        self.assertEqual([r['status'] for r in ledger['entry_dispatches']['stage']],['not_sent','sent'])
        self.assertEqual(ledger['completed'],{})

    def test_old_failures_unknown_delivery_completed_or_changed_history_stay_blocked(self):
        for entry in ({'outcome':'defeat'},{'outcome':'unknown'},{'requested':True}):
            ledger={'attempted':{'stage':entry},'completed':{}}
            self.assertFalse(can_enter(ledger,'stage'))
            self.assertTrue(can_enter(ledger,'new-stage'))
        ledger={'attempted':{},'completed':{}}
        record=reserve_entry(ledger,'stage',{'start_epoch':100})
        finish_dispatch(record,'not_sent')
        ledger['attempted']['stage']['start_epoch']=200
        self.assertFalse(can_enter(ledger,'stage'))
        ledger['attempted']['stage']['start_epoch']=100;ledger['completed']['stage']={}
        self.assertFalse(can_enter(ledger,'stage'))


def team_runner(phase='support'):
    f=frame([('进行任务',1435,829),('管理队伍',190,100),('新关卡',1300,170),('8/100',1260,827)])
    f.image[650:710,900:1095]=(0,200,0)
    r=fake_runner(f)
    r.ticket=dict(key='E4-C1-S4',name='新关卡',phase=phase,verified_epoch=time.time(),episode=4,chapter=1,stage=4)
    r.s['attempted']['E4-C1-S2']={'outcome':'defeat','evidence':'keep.png'}
    return r


class MainlineEntryTests(unittest.TestCase):
    def step(self,r):
        with patch('runner.event'),patch.object(runner,'ROOT',Path('no-live-state-test')):
            return r.step(r.frame)

    def test_map_can_open_team_directly_without_requiring_support_page(self):
        r=team_runner('map');self.step(r)
        r.back.assert_not_called();self.assertEqual(r.s['active']['key'],'E4-C1-S4')
        self.assertEqual(r.s['entry_dispatches']['E4-C1-S4'][0]['status'],'sent')

    def test_late_mouse_takeover_does_not_permanently_lock_unentered_stage(self):
        r=team_runner();saved=[];r.save.side_effect=lambda:saved.append(copy.deepcopy(r.s))
        r.action.side_effect=TapNotSent('鼠标接管，未按下')
        with self.assertRaises(TaskAttention) as caught:self.step(r)
        self.assertEqual(caught.exception.code,'entry_not_sent')
        self.assertIn('E4-C1-S4',saved[0]['attempted'])
        self.assertEqual(saved[0]['entry_dispatches']['E4-C1-S4'][0]['status'],'reserved')
        original=copy.deepcopy(r.s['attempted']);self.assertIsNone(r.s['active'])
        self.assertTrue(can_enter(r.s,'E4-C1-S4'));self.assertFalse(can_enter(r.s,'E4-C1-S2'))
        r.action.side_effect=None;self.step(r)
        self.assertEqual(r.action.call_count,2);self.assertFalse(can_enter(r.s,'E4-C1-S4'))
        self.assertEqual(r.s['attempted'],original);self.assertEqual(r.s['completed'],{})

    def test_uncertain_delivery_keeps_intent_and_never_sends_again(self):
        r=team_runner();r.action.side_effect=InputDeliveryError('unknown')
        with self.assertRaises(InputDeliveryError):self.step(r)
        self.assertFalse(can_enter(r.s,'E4-C1-S4'))
        r.action.reset_mock();r.action.side_effect=None;self.step(r)
        r.action.assert_not_called();self.assertIn('E4-C1-S4',r.s['attempted'])

    def test_durable_write_failure_stops_before_entry_input(self):
        r=team_runner();r.save.side_effect=OSError('disk full')
        with self.assertRaises(OSError):self.step(r)
        r.action.assert_not_called()

    def test_direct_team_still_checks_current_name_and_resources(self):
        r=team_runner('map');r.ticket['name']='另一个名字'
        self.step(r);r.action.assert_not_called()


class ViewportTests(unittest.TestCase):
    def test_maximized_and_common_client_sizes_accept_full_client_without_black_bars(self):
        for w,h in [(640,360),(1207,679),(1920,991),(1920,1040),(2560,1351),(1600,1000),(3840,2160)]:
            with self.subTest(size=(w,h)):
                raw=runner.np.full((h,w,3),30,runner.np.uint8)
                self.assertEqual(pc_viewport(raw),Viewport(0,0,w,h))

    def test_letterbox_offset_maps_back_to_native_client(self):
        raw=runner.np.zeros((991,1920,3),runner.np.uint8);raw[:,79:1841]=40
        vp=pc_viewport(raw);self.assertEqual(vp,Viewport(79,0,1762,991))
        self.assertEqual(vp.point(800,450),(960,495))
        raw=runner.np.zeros((1000,1600,3),runner.np.uint8);raw[50:950]=40
        self.assertEqual(pc_viewport(raw),Viewport(0,50,1600,900))

    def test_dark_scene_and_asymmetric_dark_artwork_are_not_cropped(self):
        raw=runner.np.zeros((991,1920,3),runner.np.uint8)
        self.assertEqual(pc_viewport(raw),Viewport(0,0,1920,991))
        raw[:,100:1800]=40
        self.assertEqual(pc_viewport(raw),Viewport(0,0,1920,991))

    def backend(self):
        folder=tempfile.TemporaryDirectory();self.addCleanup(folder.cleanup)
        api=FakeApi();api.window=replace(api.window,width=1920,height=991)
        raw=runner.np.zeros((991,1920,3),runner.np.uint8);raw[:,79:1841]=40
        api.capture=lambda _:raw
        b=PcBackend(dict(game_exe=api.window.exe,viewport_mode='auto',authorization_mode='selected_target',experimental_input_enabled=True),Path(folder.name)/'STOP',api=api)
        b.authorize_selected_target(api.window.identity());return b,api

    def test_mainline_capture_and_click_share_exact_viewport(self):
        b,api=self.backend();raw=b.capture();self.assertEqual(raw.shape,(991,1762,3))
        b.tap(800,450);self.assertEqual(api.calls[0],('move',(api.window.x+960,api.window.y+495)))

    def test_resize_invalidates_old_frame_but_next_capture_binds_new_geometry(self):
        b,api=self.backend();b.capture();api.window=replace(api.window,x=10)
        with self.assertRaises(PcSafetyError):b.tap(800,450)
        self.assertEqual(api.calls,[]);b.capture();b.tap(800,450)
        self.assertEqual(api.calls[0],('move',(970,api.window.y+495)))

    def test_native_tap_certifies_only_pre_press_mouse_cancellation(self):
        b,api=self.backend();b.capture()
        def button(down):
            if down:raise InputBusy('before press')
        api.button=button
        with self.assertRaises(TapNotSent):b.tap(800,450)
        b.capture();api.button=lambda down:(_ for _ in ()).throw(InputDeliveryError('unknown')) if down else None
        with self.assertRaises(InputDeliveryError):b.tap(800,450)

    def test_unified_capture_and_click_include_letterbox_offset(self):
        b,api=self.backend();t=UnifiedTransport.__new__(UnifiedTransport)
        t.api=api;t.check=lambda:None;t.ensure=lambda:api.window;t.input_tick=lambda:None
        snap=t.capture();self.assertEqual(snap.image.size,(1762,991))
        t.tap(snap,Mock(center=(881,495)))
        self.assertEqual(api.calls[0],('move',(api.window.x+960,api.window.y+495)))


class LauncherDefaultsTests(unittest.TestCase):
    def test_both_shortcuts_use_same_auto_discovery_without_overriding_task(self):
        root=Path(__file__).resolve().parents[1]
        self.assertEqual((root/'Start.cmd').read_bytes(),(root/'PCStart.cmd').read_bytes())
        text=(root/'Start.cmd').read_text();self.assertIn('--client auto',text);self.assertNotIn('--task',text)
        self.assertIn('%*',text)


class StoryCancellationTests(unittest.TestCase):
    def test_cancelled_story_press_keeps_intent_but_allows_first_actual_entry(self):
        from test_story import make,synthetic_team
        from story_core import read_stage
        f=synthetic_team('3-7');r,s=make(f);stage=read_stage(f);s.bind(stage['region'])
        r.action.side_effect=TapNotSent('not pressed')
        with self.assertRaises(TaskAttention):s.enter(f,stage,f.find('进行任务'))
        original=copy.deepcopy(s.book['attempted']);self.assertIsNone(s.book['active'])
        self.assertEqual(len(original),1);self.assertEqual(s.book['completed'],{})
        r.action.side_effect=None;s.enter(f,stage,f.find('进行任务'))
        self.assertEqual(len(s.book['attempted']),2)
        for key,value in original.items():self.assertEqual(s.book['attempted'][key],value)
        self.assertEqual(s.book['farm_runs'],0)

    def test_story_uncertain_press_remains_blocked(self):
        from test_story import make,synthetic_team
        from story_core import read_stage
        f=synthetic_team('3-7');r,s=make(f);stage=read_stage(f);s.bind(stage['region'])
        r.action.side_effect=InputDeliveryError('unknown')
        with self.assertRaises(InputDeliveryError):s.enter(f,stage,f.find('进行任务'))
        original=copy.deepcopy(s.book['attempted']);r.action.reset_mock()
        with self.assertRaises(TaskAttention):s.enter(f,stage,f.find('进行任务'))
        r.action.assert_not_called();self.assertEqual(s.book['attempted'],original)


class AbyssCancellationTests(unittest.TestCase):
    def test_worker_resumes_unpressed_entry_after_explicit_continue_with_new_frames(self):
        from types import SimpleNamespace
        from PIL import Image
        from assistant_worker import abyss_run,StopRun
        from abyss_core import Session
        from test_input_ux import prep_rows
        import os
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{},clear=False):
            root=Path(folder);history=root/'abyss-history.json'
            request=dict(home=folder,settings=dict(observe=False,task='abyss',pc_input='messages',start_policy='current_screen'),target=dict(client='pc',exe='fake.exe'))
            session=Session(normal_verified=True,expected_floor=66,entered_floor=66,phase='next_opening')
            ctl=Mock();transport=Mock();transport.input_block_reason=Mock(return_value='')
            original=[]
            def tap(*args):
                ledger=next(iter(json.loads(history.read_text())['clients'].values()))
                self.assertIn('66',ledger['attempted'])
                if not original:
                    original.append(copy.deepcopy(ledger['attempted']['66']))
                    raise TapNotSent('before press')
            transport.tap.side_effect=tap
            snapshots=[SimpleNamespace(image=Image.new('RGB',(1124,632)),captured_at=100+i) for i in range(6)]
            bank=Mock(entries=[True]);bank.apply.side_effect=lambda image,obs:obs
            with patch('assistant_transport.UnifiedTransport',return_value=transport), \
                 patch('rapidocr_onnxruntime.RapidOCR',return_value=Mock(return_value=(prep_rows(),None))), \
                 patch('abyss_templates.TemplateBank',return_value=bank), \
                 patch('abyss_core.Session',return_value=session), \
                 patch('assistant_portable.enabled',return_value=False), \
                 patch('assistant_worker.validate_run',return_value=(root,{})), \
                 patch('assistant_worker.capture_fresh',side_effect=snapshots+[StopRun()]), \
                 patch('assistant_worker.time.monotonic',return_value=100):
                with self.assertRaises(StopRun):abyss_run(request,ctl)
            ctl.attention.assert_called_once();self.assertEqual(ctl.attention.call_args.args[0].code,'entry_not_sent')
            self.assertEqual(transport.tap.call_count,2)
            self.assertIsNot(transport.tap.call_args_list[0].args[0],transport.tap.call_args_list[1].args[0])
            ledger=next(iter(json.loads(history.read_text())['clients'].values()))
            self.assertEqual(ledger['attempted']['66'],original[0])
            self.assertEqual([d['status'] for d in ledger['entry_dispatches']['66']],['not_sent','sent'])
            self.assertEqual(ledger['completed'],{});self.assertEqual(session.wins,0)
