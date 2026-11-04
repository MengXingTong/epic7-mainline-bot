"""Input arbitration/recovery with fake Win32, worker and controls. No live input."""
import ctypes
from ctypes import wintypes
from contextlib import nullcontext
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from pc_backend import WindowSnapshot, PcSafetyError, InputBusy, InputDeliveryError
from pc_message_backend import MessageWin32Api
from assistant_worker import wait_for_input, StopRun, PauseRun, abyss_run, mainline_run
from assistant_config import atomic_json
from abyss_core import Session, Scene, Reading, Observation, Token
from task_blockers import TaskAttention


class PhysicalInputTests(unittest.TestCase):
    def make(self):
        api = MessageWin32Api.__new__(MessageWin32Api)
        api.c = ctypes; api.w = wintypes; api.u = Mock()
        api.dpi = lambda: nullcontext()
        api.target = WindowSnapshot(10, 20, 'EpicSeven.exe', 30, -1920, 100, 1280, 720, 144)
        api.pending = (100, 100); api.down = False; api._post = Mock(); api.ready = Mock(return_value=True)
        self.pointer = [-200, 10]; self.pressed = set()
        def cursor(point):
            point._obj.x, point._obj.y = self.pointer
            return True
        api.u.GetCursorPos.side_effect = cursor
        api.u.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key in self.pressed else 0
        api.u.WindowFromPoint.return_value = 111
        api.u.GetAncestor.return_value = api.target.hwnd
        return api

    def test_hover_in_actual_game_client_yields_without_moving_mouse(self):
        api = self.make(); self.pointer[:] = [-1700, 200]
        self.assertIn('移出后自动继续', api.input_block_reason(api.target))
        with self.assertRaises(InputBusy):api.button(True)
        api._post.assert_not_called(); api.u.SetCursorPos.assert_not_called(); api.u.SendInput.assert_not_called()

    def test_occluding_other_app_is_not_mistaken_for_game_mouse_ownership(self):
        api = self.make(); self.pointer[:] = [-1700, 200]; api.u.GetAncestor.return_value = 999
        self.assertEqual(api.input_block_reason(api.target), '')

    def test_pointer_outside_native_client_does_not_block_or_double_scale(self):
        api = self.make(); self.pointer[:] = [-640, 200]
        self.assertEqual(api.input_block_reason(api.target), '')
        api.u.WindowFromPoint.assert_not_called()

    def test_held_mouse_or_modifier_outside_game_yields_until_release(self):
        api = self.make()
        for key in (1, 2, 4, 0x10, 0x11, 0x12):
            self.pressed = {key}; self.assertIn('松开后自动继续', api.input_block_reason(api.target))
        self.pressed.clear(); self.assertEqual(api.input_block_reason(api.target), '')

    def test_async_key_low_bit_is_not_treated_as_a_held_button(self):
        api = self.make(); api.u.GetAsyncKeyState.side_effect = None; api.u.GetAsyncKeyState.return_value = 1
        self.assertEqual(api.input_block_reason(api.target), '')

    def test_unreadable_input_desktop_waits_without_any_input(self):
        api = self.make(); api.u.GetCursorPos.side_effect = None; api.u.GetCursorPos.return_value = False
        self.assertIn('暂不可读', api.input_block_reason(api.target)); api._post.assert_not_called()

    def test_mouse_arriving_between_move_and_down_never_receives_down(self):
        api = self.make(); api.input_block_reason = Mock(side_effect=['', '鼠标进入游戏'])
        with self.assertRaises(InputBusy):api.button(True)
        self.assertEqual([c.args[0] for c in api._post.call_args_list], [0x200])
        self.assertFalse(api.down)

    def test_release_still_runs_when_mouse_takes_over_or_target_no_longer_ready(self):
        api = self.make(); api.down = True; self.pointer[:] = [-1700, 200]; api.ready.return_value = False
        api.button(False)
        self.assertEqual(api._post.call_args.args[0], 0x202)
        self.assertTrue(api._post.call_args.kwargs['release']); self.assertFalse(api.down)
        api.u.GetCursorPos.assert_not_called()

    def test_drag_takeover_stops_motion_but_releases_original_pair(self):
        api = self.make(); api.down = True; self.pointer[:] = [-1700, 200]
        try:
            with self.assertRaises(InputBusy):api.move(-1600, 300)
        finally:api.button(False)
        self.assertEqual([c.args[0] for c in api._post.call_args_list], [0x202])
        self.assertEqual(api.pending, (100, 100))

    def test_escape_is_not_sent_while_user_owns_game(self):
        api = self.make(); self.pointer[:] = [-1700, 200]
        with self.assertRaises(InputBusy):api.escape()
        api._post.assert_not_called()

    def test_minimized_failure_reports_actual_check_not_a_guessed_geometry_error(self):
        api=self.make();del api.ready;api.u.IsIconic.return_value=True
        self.assertFalse(api.ready(api.target));self.assertIn('最小化',api.last_unready_reason)
        with self.assertRaisesRegex(PcSafetyError,'最小化'):api.capture(api.target)
        api._post.assert_not_called()

    def test_unsupported_window_type_is_explained_without_claiming_resize(self):
        api=self.make();del api.ready;api.u.IsIconic.return_value=False;api.u.IsWindowVisible.return_value=True
        probe=Mock();probe.inspect.return_value=SimpleNamespace(class_name='OtherClass',width=1280,height=720)
        with patch('pc_message_backend.MessageProbe',return_value=probe):
            self.assertFalse(api.ready(api.target))
        self.assertIn('窗口类型',api.last_unready_reason);self.assertNotIn('尺寸',api.last_unready_reason)

    def test_target_probe_failure_is_recoverable_but_not_a_blank_frame_retry(self):
        from pc_message_probe import ProbeError
        from pc_message_backend import CaptureUnavailable
        api=self.make();probe=Mock();probe.capture.side_effect=ProbeError('目标窗口已变化')
        with patch('pc_message_backend.MessageProbe',return_value=probe):
            with self.assertRaises(PcSafetyError) as caught:api.capture(api.target)
        self.assertNotIsInstance(caught.exception,CaptureUnavailable)
        api._post.assert_not_called()

    def test_message_failure_is_typed_and_never_falls_back_to_foreground(self):
        api = self.make(); del api._post
        def reject(*args):ctypes.set_last_error(5);return 0
        sender = Mock(); sender.PostMessageW.side_effect = reject
        with patch('pc_message_backend.MessageProbe', return_value=SimpleNamespace(u=sender)):
            with self.assertRaises(InputDeliveryError):api._post(0x201, 1, 0)
        api.u.SendInput.assert_not_called(); api.u.SetCursorPos.assert_not_called()


class HoldTakeoverTests(unittest.TestCase):
    def test_user_takeover_during_hold_releases_original_press_and_consumes_frame(self):
        from pc_backend import PcBackend
        import numpy as np
        window=WindowSnapshot(10,20,'EpicSeven.exe',30,100,200,1600,900)
        class Api:
            def __init__(self):self.calls=[];self.down=False
            def windows(self,*args):return [window]
            def ready(self,s):return True
            def capture(self,s):return np.zeros((900,1600,3),np.uint8)
            def point_is_target(self,*args):return True
            def move(self,*args):pass
            def button(self,down):self.down=down;self.calls.append(down)
            def input_block_reason(self,s):return '用户鼠标移入' if self.down else ''
        api=Api()
        with tempfile.TemporaryDirectory() as folder:
            cfg=dict(game_exe=window.exe,experimental_input_enabled=True,authorization_mode='selected_target')
            backend=PcBackend(cfg,Path(folder)/'STOP',api=api)
            backend.capture();backend.authorize_selected_target(window.identity())
            with self.assertRaises(InputBusy):backend.hold(800,450,1)
        self.assertEqual(api.calls,[True,False]);self.assertFalse(api.down);self.assertIsNone(backend.frame_at)


class BusyBackend:
    def __init__(self, reasons):self.reasons=iter(reasons)
    def input_block_reason(self, *args):
        value=next(self.reasons)
        if isinstance(value, Exception):raise value
        return value


class WaitingTests(unittest.TestCase):
    def control(self):
        ctl=Mock(); self.clock=[100.0]
        ctl.sleep.side_effect=lambda seconds:self.clock.__setitem__(0, self.clock[0]+seconds)
        return ctl

    def test_wait_returns_refresh_signal_not_permission_to_reuse_old_frame(self):
        ctl=self.control()
        with patch('assistant_worker.time.monotonic', side_effect=lambda:self.clock[0]):
            self.assertTrue(wait_for_input(ctl, BusyBackend(['鼠标在游戏内', '鼠标在游戏内', ''])))
        self.assertEqual(ctl.status.call_args_list[0].kwargs['mode'], 'waiting_input')
        self.assertEqual(ctl.status.call_args.kwargs['mode'], 'run')
        self.assertIn('重新截图', ctl.status.call_args.args[0])

    def test_idle_or_non_pc_backend_does_not_enter_wait(self):
        ctl=self.control()
        self.assertFalse(wait_for_input(ctl, BusyBackend([''])))
        self.assertFalse(wait_for_input(ctl, None)); ctl.status.assert_not_called()

    def test_long_mouse_wait_keeps_heartbeat_instead_of_looking_hung(self):
        ctl=self.control()
        with patch('assistant_worker.time.monotonic', side_effect=lambda:self.clock[0]):
            wait_for_input(ctl, BusyBackend(['鼠标在游戏内']*360+['']))
        self.assertGreater(self.clock[0]-100, 65)
        self.assertGreaterEqual(len([c for c in ctl.status.call_args_list if c.kwargs['mode']=='waiting_input']), 30)

    def test_pause_and_stop_interrupt_wait_without_writing_or_input(self):
        for error in (PauseRun(), StopRun()):
            ctl=self.control();ctl.sleep.side_effect=error
            with self.assertRaises(type(error)):wait_for_input(ctl, BusyBackend(['鼠标在游戏内']))
            ctl.attention.assert_not_called()

    def test_geometry_failure_during_wait_is_not_automatically_retried(self):
        ctl=self.control()
        with self.assertRaises(PcSafetyError):
            wait_for_input(ctl, BusyBackend(['鼠标在游戏内', PcSafetyError('geometry changed')]))
        self.assertEqual(ctl.sleep.call_count, 1)


class NavigationRecoveryTests(unittest.TestCase):
    def clear(self):
        return Observation(1600,900,[Token('下一层',1440,800,100,40)])

    def test_verified_next_prep_can_retry_once_without_counting_or_starting_battle(self):
        s=Session();o=self.clear();r=Reading(Scene.CLEAR,floor=65)
        s.applied(s.plan(r,o));self.assertIsNone(s.plan(r,o));s.transition_until=0
        action=s.plan(r,o);self.assertEqual((action.kind,action.target_floor),('advance',66))
        s.applied(action);s.transition_until=0
        with self.assertRaises(TaskAttention):s.plan(r,o)
        self.assertEqual((s.wins,s.expected_floor,s.phase),(0,66,'next_opening'))

    def test_choose_team_navigation_can_retry_once_not_indefinitely(self):
        s=Session();o=Observation(1600,900,[Token('选择队伍',1400,800,100,40)])
        r=Reading(Scene.NORMAL,floor=66,available_floor=66)
        s.applied(s.plan(r,o));s.transition_until=0
        action=s.plan(r,o);self.assertEqual(action.kind,'choose_team');s.applied(action);s.transition_until=0
        with self.assertRaises(TaskAttention):s.plan(r,o)

    def test_entry_pending_or_previously_seen_battle_never_replays_start(self):
        for phase in ('battle_opening','battle'):
            s=Session(normal_verified=True,expected_floor=66,entered_floor=66,phase=phase,transition_until=0)
            o=Observation(1600,900,[Token('战斗开始',1400,800,100,40)])
            with self.assertRaises(TaskAttention) as caught:s.plan(Reading(Scene.TEAM,floor=66),o)
            self.assertEqual(caught.exception.code,'entry_uncertain')
            self.assertEqual(s.expected_floor,66)


def prep_rows():
    words=[('准备战斗',148,42),('深渊',1194,110),('第66层',1204,160),('战斗开始',1441,820)]
    return [([[x-20,y-10],[x+20,y-10],[x+20,y+10],[x-20,y+10]],text,.99) for text,x,y in words]


class WorkerRecoveryTests(unittest.TestCase):
    def exercise(self, delivery_error=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);history_path=root/'abyss-history.json';key=hashlib.sha256(b'pc|fake.exe').hexdigest()[:24]
            atomic_json(history_path,{'schema':1,'clients':{key:{'attempted':{'65':{'keep':True}},'completed':{'65':{}}}}})
            request=dict(home=folder,settings=dict(observe=False,task='abyss',pc_input='messages'),target=dict(client='pc',exe='fake.exe'))
            session=Session(normal_verified=True,expected_floor=66,entered_floor=66,phase='next_opening')
            ctl=Mock();clock=[100.0];ctl.sleep.side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
            snapshots=[SimpleNamespace(image=Image.new('RGB',(1124,632)),captured_at=100+i) for i in range(4)]
            owner=self
            class Transport:
                def __init__(self):self.reads=0;self.tap=Mock(side_effect=self.enter);self.swipe=Mock();self.capture=Mock()
                def input_block_reason(self,frame):
                    ledger=json.loads(history_path.read_text())['clients'][key]
                    owner.assertNotIn('66',ledger['attempted'])
                    self.reads+=1
                    return '鼠标位于游戏客户区' if not delivery_error and self.reads<=3 else ''
                def enter(self,frame,token,ordinary_gate=False):
                    ledger=json.loads(history_path.read_text())['clients'][key]
                    owner.assertIn('66',ledger['attempted']);owner.assertNotIn('66',ledger['completed'])
                    owner.assertEqual(session.phase,'battle_opening')
                    if delivery_error:raise InputDeliveryError('模拟系统发送失败；不回退输入方式')
                    owner.assertIs(frame,snapshots[3])
            transport=Transport();events=[];saved=[]
            def attention(exc):
                events.append(exc)
                if delivery_error and len(events)==1:
                    saved.append(history_path.read_bytes());clock[0]+=30;return
                raise StopRun()
            ctl.attention.side_effect=attention
            templates=Mock(entries=[True]);templates.apply.side_effect=lambda image,obs:obs
            with patch('assistant_transport.UnifiedTransport',return_value=transport), \
                 patch('rapidocr_onnxruntime.RapidOCR',return_value=Mock(return_value=(prep_rows(),None))), \
                 patch('abyss_templates.TemplateBank',return_value=templates), \
                 patch('abyss_core.Session',return_value=session), \
                 patch('assistant_portable.enabled',return_value=False), \
                 patch('assistant_worker.validate_run',return_value=(root,{})), \
                 patch('assistant_worker.capture_fresh',side_effect=snapshots+[StopRun()]) as capture, \
                 patch('assistant_worker.time.monotonic',side_effect=lambda:clock[0]):
                with self.assertRaises(StopRun):abyss_run(request,ctl)
            transport.tap.assert_called_once();transport.swipe.assert_not_called()
            ledger=json.loads(history_path.read_text())['clients'][key]
            self.assertEqual(ledger['attempted']['65'],{'keep':True});self.assertEqual(session.wins,0)
            if delivery_error:
                self.assertEqual(len(events),2);self.assertEqual(events[-1].code,'entry_uncertain')
                self.assertEqual(history_path.read_bytes(),saved[0])
            else:
                ctl.attention.assert_not_called();self.assertEqual(capture.call_count,5)
                self.assertTrue(any(c.kwargs.get('mode')=='waiting_input' for c in ctl.status.call_args_list))

    def test_hover_wait_precedes_entry_record_and_requires_two_new_frames(self):self.exercise()
    def test_delivery_error_keeps_worker_context_and_intent_without_replaying_start(self):self.exercise(True)

    def exercise_mainline(self, status='安全暂停待修复', input_error=False):
        import runner
        instances=[]
        class FakeRunner:
            def __init__(self,**kwargs):
                self.pc=None;self.s={'completed':{},'attempted':{'old':{'keep':True}},'active':{'key':'old'}}
                self.ticket={'key':'current'};self.mode_since=0;self.input_sequence=0;instances.append(self)
            def start_current_screen(self):pass
            def capture(self):return SimpleNamespace(image=runner.np.zeros((900,1600,3),runner.np.uint8))
            def step(self,frame):
                if input_error:raise InputBusy('鼠标恰好移入')
                return self.stop(status,'模拟临时流程阻塞')
            def stop(self,status,reason):self.s['terminal']=True;return False,0
            def save(self):pass
        ctl=Mock();resumed=[]
        def resume_once(exc):
            resumed.append(exc)
            if len(resumed)>1:raise StopRun()
        ctl.attention.side_effect=resume_once
        story=SimpleNamespace(total_wins=lambda:0,context=False,stage_label=lambda:'')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{},clear=False):
            root=Path(folder)
            request=dict(run_dir=folder,settings=dict(observe=False,task='mainline',mumu={}),
                         target=dict(client='mumu',serial='fake',package='fake'))
            with patch('assistant_worker.validate_run',return_value=(root,{})),patch.object(runner,'ROOT',root), \
                 patch('runner.Runner',FakeRunner),patch('runner.classify',return_value='unknown'), \
                 patch('story_core.StoryController',return_value=story), \
                 patch('assistant_worker.ScreenStabilityGate',return_value=Mock(waiting=Mock(return_value=False))):
                if status=='强度不足卡关' and not input_error:mainline_run(request,ctl)
                else:
                    with self.assertRaises(StopRun):mainline_run(request,ctl)
        self.assertEqual(instances[0].s['attempted'],{'old':{'keep':True}})
        if status=='强度不足卡关' and not input_error:
            ctl.attention.assert_not_called();self.assertTrue(instances[0].s['terminal'])
        else:
            self.assertEqual(ctl.attention.call_count,2);self.assertNotIn('terminal',instances[0].s)
            self.assertEqual(instances[0].ticket,{'key':'current'})
            if input_error:
                self.assertNotIn('自动继续',ctl.attention.call_args.args[0].reason)
                self.assertIn('点继续',ctl.attention.call_args.args[0].reason)

    def test_mainline_soft_flow_waits_without_terminal_or_process_exit(self):self.exercise_mainline()
    def test_mainline_late_input_conflict_waits_without_clearing_context(self):self.exercise_mainline(input_error=True)
    def test_mainline_defeat_remains_terminal_not_automatically_resumed(self):self.exercise_mainline(status='强度不足卡关')


if __name__=='__main__':unittest.main()
