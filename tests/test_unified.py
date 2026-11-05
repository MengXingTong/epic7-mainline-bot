"""Unified control/transport tests: all native calls are fakes; never send input."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from assistant_config import select_target,validate_run,gate_mainline,load_settings,reserve_abyss_entry,window_layout
from assistant_worker import Control,PauseRun,StopRun,GuardedApi
from assistant_transport import UnifiedTransport,FrameSnapshot
from pc_backend import WindowSnapshot,PcSafetyError
from pc_message_backend import MessageWin32Api

PC=dict(client='pc',hwnd=10,pid=20,created=30,exe='EpicSeven.exe',title='第七史诗',label='PC')
MU=dict(client='mumu',serial='127.0.0.1:16384',package='com.stove.epic7.google',label='MuMu')
class SelectionTests(unittest.TestCase):
    def test_auto_unique(self):self.assertEqual(select_target('auto',[PC]),PC)
    def test_auto_multiple_never_switches(self):
        with self.assertRaises(ValueError):select_target('auto',[PC,MU])
    def test_explicit_client(self):self.assertEqual(select_target('mumu',[PC,MU]),MU)
    def test_multiple_instances_need_selection(self):
        with self.assertRaises(ValueError):select_target('pc',[PC,{**PC,'pid':21}])
    def test_absent_client(self):
        with self.assertRaises(ValueError):select_target('mumu',[PC])
    def test_unknown_client(self):
        with self.assertRaises(ValueError):select_target('surprise',[PC])

class DefaultStoryTaskTests(unittest.TestCase):
    def test_fresh_configuration_defaults_to_story_not_abyss(self):
        with tempfile.TemporaryDirectory() as folder,patch('assistant_config.CODE_ROOT',Path(folder)),patch('assistant_portable.enabled',return_value=False),patch('assistant_portable.registered_root',return_value=None):
            self.assertEqual(load_settings(Path(folder))['task'],'mainline')

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.state={'attempted':{'S10':{'outcome':'defeat'}},'completed':{'S9':{}},'active':{'key':'S10'},'terminal':True,'status':'战败'}
        (self.root/'state.json').write_text(json.dumps(self.state),encoding='utf-8')
        self.before=(self.root/'state.json').read_bytes()
        self.settings=dict(data_dir=str(self.root),task='mainline',observe=False,limit=3,pc_input='messages')
    def tearDown(self):
        self.assertEqual((self.root/'state.json').read_bytes(),self.before);self.temp.cleanup()
    def test_failed_mainline_blocked(self):
        with self.assertRaisesRegex(ValueError,'S10'):validate_run(self.settings,PC)
    def test_read_only_can_inspect_failed_history(self):validate_run({**self.settings,'observe':True},PC)
    def test_abyss_does_not_reset_mainline_terminal(self):validate_run({**self.settings,'task':'abyss'},PC)
    def test_unknown_task_rejected(self):
        with self.assertRaises(ValueError):validate_run({**self.settings,'task':'challenge'},PC)
    def test_old_limit_values_do_not_restrict_direct_start(self):
        for value in (0,1,30,31,999999,None,'obsolete'):
            validate_run({**self.settings,'start_policy':'current_screen','limit':value},PC)
    def test_missing_history_not_created(self):
        missing=self.root/'not-created'
        with self.assertRaises(ValueError):validate_run({**self.settings,'data_dir':str(missing)},PC)
        self.assertFalse(missing.exists())
    def test_bad_input_mode(self):
        with self.assertRaises(ValueError):validate_run({**self.settings,'pc_input':'inject'},PC)
    def test_terminal_even_without_active_is_blocked(self):
        with self.assertRaises(ValueError):gate_mainline({'terminal':True})
    def test_stop_marker_blocks_entry(self):
        with self.assertRaises(ValueError):gate_mainline({},True)
    def test_existing_abyss_attempt_cannot_be_replaced(self):
        ledger={'attempted':{'58':{'first':'keep'}},'completed':{}}
        before=copy.deepcopy(ledger)
        with self.assertRaises(ValueError):reserve_abyss_entry(ledger,58,{'new':True})
        self.assertEqual(ledger,before)
    def test_abyss_intent_records_once(self):
        ledger={'attempted':{},'completed':{}}
        reserve_abyss_entry(ledger,58,{'requested':True});self.assertTrue(ledger['attempted']['58']['requested'])
        with self.assertRaises(ValueError):reserve_abyss_entry(ledger,58,{})
    def test_invalid_floor(self):
        with self.assertRaises(ValueError):reserve_abyss_entry({'attempted':{}},0,{})

class ControlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.control=Control(dict(run_dir=str(self.folder),run_id='new',settings={'task':'abyss'},target=PC))
    def tearDown(self):self.temp.cleanup()
    def command(self,action,run='new'):(self.folder/'control.json').write_text(json.dumps({'run_id':run,'action':action}),encoding='utf-8')
    def test_missing_controller_stops(self):
        with self.assertRaises(StopRun):self.control.check()
    def test_old_controller_cannot_resume_new_worker(self):
        self.command('run','old')
        with self.assertRaises(StopRun):self.control.check()
    def test_pause_is_not_a_click(self):
        self.command('pause')
        with self.assertRaises(PauseRun):self.control.check()
    def test_explicit_stop(self):
        self.command('stop')
        with self.assertRaises(StopRun):self.control.check()
    def test_explicit_run(self):self.command('run');self.control.check()
    def test_pause_blocks_down_but_never_blocks_release(self):
        native=Mock();ctl=Mock();ctl.check.side_effect=PauseRun()
        api=GuardedApi(native,ctl)
        with self.assertRaises(PauseRun):api.button(True)
        native.button.assert_not_called();api.button(False);native.button.assert_called_once_with(False)

class MessageApiTests(unittest.TestCase):
    def make(self):
        api=MessageWin32Api.__new__(MessageWin32Api)
        api.target=WindowSnapshot(10,20,'EpicSeven.exe',30,100,200,1600,900)
        api.pending=None;api.down=False;api.ready=Mock(return_value=True);api._post=Mock()
        api.input_block_reason=Mock(return_value='')
        return api
    def test_move_only_records_local_coordinates(self):
        api=self.make();api.move(900,650)
        self.assertEqual(api.pending,(800,450));api._post.assert_not_called()
    def test_no_point_no_click(self):
        api=self.make()
        with self.assertRaises(PcSafetyError):api.button(True)
    def test_paired_messages_no_activation_or_cursor_api(self):
        api=self.make();api.move(900,650)
        with patch('pc_message_backend.time.sleep'):api.button(True);api.button(False)
        self.assertEqual([a.args[0] for a in api._post.call_args_list],[0x200,0x201,0x202]);self.assertFalse(api.down)
    def test_default_press_remains_seventy_ms(self):
        api=self.make();api.move(900,650)
        with patch('pc_message_backend.time.sleep') as sleep:api.button(True);api.button(False)
        sleep.assert_called_once_with(.07)
    def test_short_press_keeps_paired_messages_and_checks_mouse_takeover(self):
        api=self.make();api.move(900,650)
        with patch('pc_message_backend.time.sleep') as sleep:
            api.button(True,press_seconds=.01);api.button(False)
        sleep.assert_called_once_with(.01)
        self.assertEqual([a.args[0] for a in api._post.call_args_list],[0x200,0x201,0x202])
        api._post.reset_mock();api.input_block_reason.return_value='mouse takeover'
        with self.assertRaises(PcSafetyError):api.button(True,press_seconds=.01)
        api._post.assert_not_called()
    def test_invalid_short_press_never_sends_messages(self):
        for duration in (0,-1,.071,float('nan'),float('inf'),True,'0.01',None):
            with self.subTest(duration=duration):
                api=self.make();api.move(900,650)
                with self.assertRaises(PcSafetyError):api.button(True,press_seconds=duration)
                api._post.assert_not_called()
    def test_unpaired_down_rejected(self):
        api=self.make();api.pending=(10,10);api.down=True
        with self.assertRaises(PcSafetyError):api.button(True)
    def test_release_after_geometry_change(self):
        api=self.make();api.pending=(10,10);api.down=True;api.ready.return_value=False
        api.button(False);self.assertTrue(api._post.call_args.kwargs['release']);self.assertFalse(api.down)
    def test_drag_messages_hold_left_button(self):
        api=self.make();api.down=True;api.move(900,650)
        self.assertEqual(api._post.call_args.args[0:2],(0x200,1))
    def test_out_of_client_blocked(self):
        api=self.make()
        with self.assertRaises(PcSafetyError):api.move(50,50)
        api._post.assert_not_called()
    def test_escape_uses_key_pair_only(self):
        api=self.make()
        with patch('pc_message_backend.time.sleep'):api.escape()
        self.assertEqual([a.args[0] for a in api._post.call_args_list],[0x100,0x101])
    def test_message_rejection_has_no_sendinput_fallback(self):
        api=self.make();del api._post
        api.c=SimpleNamespace(set_last_error=Mock(),get_last_error=Mock(return_value=5))
        u=Mock();u.PostMessageW.return_value=0
        with patch('pc_message_backend.MessageProbe',return_value=SimpleNamespace(u=u)):
            with self.assertRaisesRegex(PcSafetyError,'不回退输入方式'):api._post(0x201,1,0)
        self.assertEqual(u.method_calls,[unittest.mock.call.PostMessageW(10,0x201,1,0)])

class FrameGuardTests(unittest.TestCase):
    def make(self):
        transport=UnifiedTransport.__new__(UnifiedTransport);transport.check=lambda:None;transport.background=True
        transport.api=Mock();transport.api.point_is_target.return_value=True;transport.api.ready.return_value=True
        binding=WindowSnapshot(10,20,'EpicSeven.exe',30,100,200,1600,900)
        f=FrameSnapshot(Image.new('RGB',(1600,900)),binding,time.monotonic())
        transport.frame=f;transport.ensure=lambda:binding;transport.last_input=None;transport.input_tick=lambda:None
        return transport,f
    def token(self,x,y):return SimpleNamespace(center=(x,y))
    def test_lower_challenge_region_veto(self):
        t,f=self.make()
        with self.assertRaisesRegex(RuntimeError,'右上方的普通深渊'):t.tap(f,self.token(1450,650),True)
        t.api.button.assert_not_called()
    def test_stale_frame_never_clicks(self):
        t,f=self.make();f.captured_at-=10
        with self.assertRaises(RuntimeError):t.tap(f,self.token(800,400))
        t.api.button.assert_not_called()
    def test_short_press_still_consumes_frame_and_rejects_stale_target(self):
        t,f=self.make();t.tap(f,self.token(800,400),press_seconds=.01)
        self.assertEqual(t.api.button.call_args_list,[unittest.mock.call(True,press_seconds=.01),unittest.mock.call(False)])
        with self.assertRaises(PcSafetyError):t.tap(f,self.token(800,400),press_seconds=.01)
        t,f=self.make();f.captured_at-=10
        with self.assertRaises(PcSafetyError):t.tap(f,self.token(800,400),press_seconds=.01)
        t.api.button.assert_not_called()
    def test_other_frame_never_clicks(self):
        t,f=self.make();t.frame=None
        with self.assertRaises(RuntimeError):t.tap(f,self.token(800,400))
    def test_geometry_change_never_clicks(self):
        t,f=self.make();t.ensure=lambda:'new geometry'
        with self.assertRaises(RuntimeError):t.tap(f,self.token(800,400))
        t.api.button.assert_not_called()
    def test_point_is_inside_client(self):
        t,f=self.make()
        with self.assertRaises(RuntimeError):t.tap(f,self.token(1800,400))
    def test_frame_consumed_before_input_and_not_reused(self):
        t,f=self.make()
        def down(value):self.assertIsNone(t.frame)
        t.api.button.side_effect=down;t.tap(f,self.token(800,400))
        with self.assertRaises(RuntimeError):t.tap(f,self.token(800,400))
        self.assertEqual(t.api.button.call_count,2)
    def test_cancellation_before_input(self):
        t,f=self.make();t.check=Mock(side_effect=StopRun())
        with self.assertRaises(StopRun):t.tap(f,self.token(800,400))
        t.api.button.assert_not_called()


class WindowLayoutTests(unittest.TestCase):
    def test_workarea_bounds_at_common_and_scaled_sizes(self):
        for width,height in ((1920,1040),(1536,832),(1280,680),(1024,728),(640,440),(480,300)):
            with self.subTest(size=(width,height)):
                layout=window_layout((0,0,width,height),(width,height+40))
                self.assertLessEqual(layout['x']+layout['width'],width)
                self.assertLessEqual(layout['y']+layout['height']+30,height)
                self.assertLessEqual(layout['min_height'],layout['height'])
                self.assertLessEqual(layout['min_width'],layout['width'])
    def test_taskbar_workarea_not_fullscreen_height(self):
        layout=window_layout((0,0,1536,800),(1536,864))
        self.assertLessEqual(layout['y']+layout['height']+30,800)
    def test_negative_origin_math(self):
        layout=window_layout((-1536,0,0,832),(1536,864))
        self.assertGreaterEqual(layout['x'],-1536);self.assertLessEqual(layout['x']+layout['width'],0)
