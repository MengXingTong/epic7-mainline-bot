"""PC transport tests use fakes only; never instantiate the native Windows API."""
import copy,json,os,sys,tempfile,time,unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from pc_backend import PcBackend,PcSafetyError,WindowSnapshot
from state_tools import manual_clear
from runtime_paths import data_root,config_path,exclusive_profile
from pc_profile import account_preflight
import runner
import pc_launcher

class FakeApi:
    def __init__(self):
        self.window=WindowSnapshot(10,20,r'C:\Games\EpicSeven.exe',30,-1920,30,1600,900,120)
        self.candidates=None;self.focus=True;self.covered=False;self.calls=[]
        self.on_move=None;self.on_down=None;self.on_capture=None
    def windows(self,*args):return self.candidates if self.candidates is not None else [self.window]
    def ready(self,w):return self.focus
    def capture(self,w):
        result=runner.np.zeros((w.height,w.width,3),runner.np.uint8)
        if self.on_capture:self.on_capture()
        return result
    def point_is_target(self,*a):return not self.covered
    def move(self,*a):
        self.calls.append(('move',a))
        if self.on_move:self.on_move()
    def button(self,down):
        self.calls.append(('button',down))
        if down and self.on_down:self.on_down()
    def escape(self):self.calls.append(('escape',))

class PcTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.api=FakeApi();self.clock=[100.]
        self.cfg={'game_exe':self.api.window.exe,'server':'Test realm','account_id':'12345','experimental_input_enabled':True}
        with patch('pc_backend.Win32Api',side_effect=AssertionError('Native API must not run in tests')):
            self.b=PcBackend(self.cfg,self.root/'STOP',api=self.api,clock=lambda:self.clock[0])
    def proof(self):return dict(server='Test realm',account_id='12345',window=self.api.window.identity(),checked_at=time.time())
    def ready(self):self.b.capture();self.b.authorize(self.proof())
    def test_selected_target_authorization_needs_no_account_proof(self):
        self.cfg.update(authorization_mode='selected_target');self.cfg.pop('server');self.cfg.pop('account_id')
        self.b.authorize_selected_target(self.api.window.identity());self.b.capture();self.b.tap(800,450)
        self.assertEqual([k for k,v in self.api.calls],['move','button','button'])
    def test_selected_target_authorization_is_explicit_and_pinned(self):
        with self.assertRaises(PcSafetyError):self.b.authorize_selected_target(self.api.window.identity())
        self.cfg.update(authorization_mode='selected_target')
        wrong={**self.api.window.identity(),'pid':99}
        with self.assertRaises(PcSafetyError):self.b.authorize_selected_target(wrong)
        self.assertEqual(self.api.calls,[])
    def test_selected_target_still_requires_a_fresh_frame(self):
        self.cfg.update(authorization_mode='selected_target');self.b.authorize_selected_target(self.api.window.identity())
        with self.assertRaises(PcSafetyError):self.b.tap(800,450)
        self.b.capture();self.clock[0]+=6
        with self.assertRaises(PcSafetyError):self.b.tap(800,450)
        self.assertEqual(self.api.calls,[])
    def test_no_input_without_account_preflight(self):
        self.b.capture()
        with self.assertRaises(PcSafetyError):self.b.tap(800,450)
        self.assertEqual(self.api.calls,[])
    def test_experimental_input_disabled_by_default(self):
        self.cfg['experimental_input_enabled']=False
        with self.assertRaises(PcSafetyError):self.b.authorize(self.proof())
    def test_wrong_account_and_server_are_blocked(self):
        for k in ('server','account_id'):
            proof=self.proof();proof[k]='wrong'
            with self.subTest(key=k),self.assertRaises(PcSafetyError):self.b.authorize(proof)
    def test_expired_and_future_proof_are_blocked(self):
        for delta in (-121,60):
            proof=self.proof();proof['checked_at']+=delta
            with self.subTest(delta=delta),self.assertRaises(PcSafetyError):self.b.authorize(proof)
    def test_changed_process_requires_new_binding(self):
        self.b.capture();self.api.window=replace(self.api.window,pid=99)
        with self.assertRaises(PcSafetyError):self.b.capture()
    def test_multiple_windows_are_blocked(self):
        self.api.candidates=[self.api.window,self.api.window]
        with self.assertRaises(PcSafetyError):self.b.capture()
    def test_unfocused_minimized_or_covered_window_is_blocked(self):
        self.api.focus=False
        with self.assertRaises(PcSafetyError):self.b.capture()
    def test_stale_frame_is_blocked(self):
        self.ready();self.clock[0]+=5.1
        with self.assertRaises(PcSafetyError):self.b.tap(800,450)
        self.assertEqual(self.api.calls,[])
    def test_changed_geometry_or_dpi_before_input_is_blocked(self):
        for change in ({'x':-1800},{'width':1590},{'dpi':96}):
            with self.subTest(change=change):
                self.setUp();self.ready();self.api.window=replace(self.api.window,**change)
                with self.assertRaises(PcSafetyError):self.b.tap(800,450)
                self.assertEqual(self.api.calls,[])
    def test_geometry_change_during_capture_is_blocked(self):
        self.api.on_capture=lambda:setattr(self.api,'window',replace(self.api.window,x=-1800))
        with self.assertRaises(PcSafetyError):self.b.capture()
    def test_capture_size_mismatch_is_blocked(self):
        self.api.capture=lambda w:runner.np.zeros((10,10,3),runner.np.uint8)
        with self.assertRaises(PcSafetyError):self.b.capture()
    def test_point_obstruction_is_blocked(self):
        self.ready();self.api.covered=True
        with self.assertRaises(PcSafetyError):self.b.tap(800,450)
        self.assertEqual(self.api.calls,[])
    def test_point_obstruction_after_cursor_move_is_blocked(self):
        self.ready();self.api.on_move=lambda:setattr(self.api,'covered',True)
        with self.assertRaises(PcSafetyError):self.b.tap(800,450)
        self.assertFalse(any(c[0]=='button' for c in self.api.calls))
    def test_stop_marker_is_rechecked_before_input(self):
        self.ready();(self.root/'STOP').write_text('user')
        with self.assertRaises(PcSafetyError):self.b.tap(800,450)
        self.assertEqual(self.api.calls,[])
    def test_negative_monitor_coordinates_and_single_consumed_click(self):
        self.ready();self.b.tap(800,450)
        self.assertEqual(self.api.calls,[('move',(-1120,480)),('button',True),('button',False)])
        with self.assertRaises(PcSafetyError):self.b.tap(800,450)
        self.assertEqual(len(self.api.calls),3)
    def test_unknown_mouse_down_result_is_released_and_not_retried(self):
        self.ready()
        def fail():raise RuntimeError('unknown input outcome')
        self.api.on_down=fail
        with self.assertRaises(RuntimeError):self.b.tap(800,450)
        self.assertEqual(self.api.calls[-1],('button',False))
        with self.assertRaises(PcSafetyError):self.b.tap(800,450)
    def test_hold_releases_button_if_focus_is_lost(self):
        self.ready();self.api.on_down=lambda:setattr(self.api,'focus',False)
        with self.assertRaises(PcSafetyError):self.b.hold(800,450,.1)
        self.assertEqual(self.api.calls[-1],('button',False));self.assertIsNone(self.b.frame_at)
    def test_resize_support_requires_explicit_opt_in(self):
        self.api.window=replace(self.api.window,height=793)
        with self.assertRaises(PcSafetyError):self.b.capture()
        self.cfg['allow_stretched_client']=True;self.b.capture()
    def test_points_outside_game_are_rejected(self):
        self.ready()
        for xy in ((-1,0),(1600,0),(0,900)):
            with self.subTest(xy=xy),self.assertRaises(PcSafetyError):self.b.tap(*xy)
        self.assertEqual(self.api.calls,[])
    def test_escape_requires_fresh_focus_and_consumes_frame(self):
        self.ready();self.b.back()
        self.assertEqual(self.api.calls,[('escape',)])
        with self.assertRaises(PcSafetyError):self.b.back()
    def test_existing_active_profile_cannot_start_or_resume(self):
        import types
        state={'active':{'key':'E3-C3-S9'},'attempted':{'E3-C3-S9':{'outcome':'defeat'}}}
        before=copy.deepcopy(state)
        for command in ('start','resume'):
            with self.subTest(command=command),patch.object(pc_launcher,'read_frame') as capture:
                with self.assertRaisesRegex(RuntimeError,'未结算/失败'):pc_launcher.run(types.SimpleNamespace(command=command),{'pc':self.cfg},self.root,state)
                capture.assert_not_called();self.assertEqual(state,before)
    def test_bound_history_cannot_be_reassigned_to_another_account(self):
        cfg={'backend':'stove_pc','data_dir':str(self.root),'pc':self.cfg}
        state={'attempted':{},'completed':{},'pc_profile_binding':{'server':'Other realm','account_id':'12345'}}
        (self.root/'state.json').write_text(json.dumps(state));path=self.root/'config.json';path.write_text(json.dumps(cfg))
        with self.assertRaisesRegex(RuntimeError,'another PC account/server'):pc_launcher.load_settings(path)
        self.assertEqual(json.loads((self.root/'state.json').read_text()),state)

    def test_readonly_check_with_active_history_does_not_mutate_or_input(self):
        import types
        frame=self.fake_settings();self.b.capture();state={'active':{'key':'E3-C3-S9'},'attempted':{'x':{}}};before=copy.deepcopy(state)
        with patch.object(pc_launcher,'read_frame',return_value=(self.b,frame,self.root)):
            pc_launcher.run(types.SimpleNamespace(command='check',delay=2),{'pc':self.cfg},self.root,state)
        self.assertEqual(state,before);self.assertEqual(self.api.calls,[]);self.assertTrue((self.root/'preflight.json').is_file())
    def fake_settings(self,server='Test realm',uid='12345',extra=None):
        words=[('账号信息',250,140),('服务器账号编号',300,550),(server,1250,440),(uid,1400,550)]
        if extra:words.append((extra,800,500))
        rows=[([[x-10,y-10],[x+10,y-10],[x+10,y+10],[x-10,y+10]],t,.999) for t,x,y in words]
        return runner.Frame(runner.np.zeros((900,1600,3),runner.np.uint8),rows)
    def test_account_preflight_exact_field_matches(self):
        proof=account_preflight(self.fake_settings(),self.cfg,self.api.window)
        self.assertEqual(proof['account_id'],'12345');self.assertEqual(proof['window'],self.api.window.identity())
    def test_account_preflight_wrong_server_or_uid_is_rejected(self):
        for values in (('Wrong realm','12345'),('Test realm','123456')):
            with self.subTest(values=values),self.assertRaises(ValueError):account_preflight(self.fake_settings(*values),self.cfg,self.api.window)
    def test_resource_veto_overrides_correct_account_fields(self):
        with self.assertRaises(ValueError):account_preflight(self.fake_settings(extra='是否消耗道具兑换体力'),self.cfg,self.api.window)
    def test_shared_profile_lock_rejects_another_writer(self):
        with exclusive_profile(self.root):
            with self.assertRaises(RuntimeError):
                with exclusive_profile(self.root):pass
        with exclusive_profile(self.root):pass
    def test_runtime_paths_do_not_require_copying_or_clearing_history(self):
        with patch.dict(os.environ,{'EPIC7_DATA_DIR':str(self.root),'EPIC7_CONFIG_PATH':str(self.root/'pc-runtime.json')}):
            self.assertEqual(data_root(),self.root.resolve());self.assertEqual(config_path(),(self.root/'pc-runtime.json').resolve())

class ResolutionTests(unittest.TestCase):
    def test_client_coordinate_matrix_without_double_dpi_scaling(self):
        for width,height in ((640,360),(960,540),(1024,576),(1280,720),(1600,900),(1920,1080),(2560,1440),(3840,2160)):
            for dpi in (96,120,144,168,192):
                for origin in ((0,30),(-3840,50),(1920,-1440)):
                    with self.subTest(size=(width,height),dpi=dpi,origin=origin):
                        w=WindowSnapshot(1,2,'game.exe',3,*origin,width,height,dpi)
                        self.assertEqual(w.point(0,0),origin)
                        self.assertEqual(w.point(800,450),(origin[0]+width//2,origin[1]+height//2))
                        x,y=w.point(1599.99,899.99)
                        self.assertTrue(origin[0]<=x<origin[0]+width and origin[1]<=y<origin[1]+height)
    def test_runner_normalizes_client_only_at_different_resolutions(self):
        import types
        for width,height in ((640,360),(1024,576),(1280,720),(1600,900),(1920,1080),(2560,1440),(3840,2160),(1536,793)):
            with self.subTest(size=(width,height)),tempfile.TemporaryDirectory() as tmp:
                r=runner.Runner.__new__(runner.Runner);r.s={};r.ocr=lambda image:([],None)
                r.pc=types.SimpleNamespace(capture=lambda:runner.np.zeros((height,width,3),runner.np.uint8))
                with patch.object(runner,'ROOT',Path(tmp)):
                    f=r.capture()
                self.assertEqual(f.image.shape,(900,1600,3));self.assertEqual(f.raw_size,(width,height))
    def test_small_client_is_safely_rejected_not_required_to_be_fullscreen(self):
        api=FakeApi();api.window=replace(api.window,width=625,height=352)
        with tempfile.TemporaryDirectory() as tmp:
            b=PcBackend({'game_exe':api.window.exe},Path(tmp)/'STOP',api=api)
            with self.assertRaisesRegex(PcSafetyError,'too small'):b.capture()
            self.assertEqual(api.calls,[])
    def test_readonly_backend_can_inspect_stop_but_never_input(self):
        api=FakeApi()
        with tempfile.TemporaryDirectory() as tmp:
            stop=Path(tmp)/'STOP';stop.write_text('user')
            b=PcBackend({'game_exe':api.window.exe,'experimental_input_enabled':True},stop,api=api,read_only=True)
            b.capture()
            with self.assertRaises(PcSafetyError):b.authorize({})
            with self.assertRaises(PcSafetyError):b.tap(800,450)
            with self.assertRaises(PcSafetyError):b.back()
            self.assertTrue(stop.exists());self.assertEqual(api.calls,[])
    @unittest.skipUnless(os.name=='nt','Win32 ABI declarations are checked only on Windows')
    def test_x64_input_abi_and_gdi_prototypes_without_native_calls(self):
        import ctypes
        from unittest.mock import MagicMock
        from pc_backend import Win32Api
        with patch.object(ctypes,'WinDLL',side_effect=lambda *a,**k:MagicMock()):
            api=Win32Api()
        self.assertEqual(ctypes.sizeof(api.Input),40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)
        self.assertEqual(len(api.u.SendInput.argtypes),3);self.assertEqual(len(api.g.GetDIBits.argtypes),7)
        api.u.GetForegroundWindow.assert_not_called();api.u.SendInput.assert_not_called()


class StartupAndCgTests(unittest.TestCase):
    def test_pc_initialization_failure_preserves_active_and_all_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=root/'pc.json';cfg.write_text('{"backend":"stove_pc"}')
            state={'active':{'key':'stage'},'attempted':{'stage':{'outcome':'unknown'}},'completed':{'older':{}},'network_retries':[1,2]}
            (root/'state.json').write_text(json.dumps(state))
            with patch.object(runner,'ROOT',root),patch.object(runner,'config_path',return_value=cfg):
                self.assertTrue(runner.record_pc_startup_failure(RuntimeError('focus lost')))
            after=json.loads((root/'state.json').read_text(encoding='utf8'))
            self.assertTrue(after['terminal'])
            for key in state:self.assertEqual(after[key],state[key])
    def test_game_login_and_server_screens_are_not_cg_click_targets(self):
        for text in ('轻触画面开始','轻触屏幕开始','服务器','账号验证','STOVE'):
            with self.subTest(text=text):
                frame=runner.Frame(runner.np.full((900,1600,3),50,runner.np.uint8),[([[700,400],[900,400],[900,450],[700,450]],text,.999)])
                r=runner.Runner.__new__(runner.Runner);r.frame=frame;r.ticket=None;r.last_mode='unknown';r.mode_since=time.time()-15;r.battle_seen=0;r.last_gesture=0;r.unknown_gestures=0
                r.s={'active':{'key':'stage'},'completed':{},'attempted':{}};r.cfg={};r.save=lambda:None;r.action=unittest.mock.Mock()
                with patch.object(runner,'event'):
                    r.step(frame)
                r.action.assert_not_called();self.assertEqual(r.unknown_gestures,0)


class ManualClearTests(unittest.TestCase):
    def setUp(self):
        self.node={'key':'E3-C3-S9','episode':3,'chapter':3,'stage':9}
        self.state={'terminal':True,'active':copy.deepcopy(self.node),'attempted':{'E3-C3-S9':{**self.node,'outcome':'defeat','evidence':'old.png'}},'completed':{'older':{'evidence':'older.png'}},'network_retries':[1,2,3],'last_cleared':{'key':'older'}}
    def test_manual_clear_preserves_failed_attempt_and_all_unrelated_history(self):
        before=copy.deepcopy(self.state);after=manual_clear(self.state,self.node,'已通关绿色勾','new.png','now')
        self.assertEqual(self.state,before);self.assertEqual(after['attempted']['E3-C3-S9']['outcome'],'defeat')
        self.assertEqual(after['attempted']['E3-C3-S9']['evidence'],'old.png');self.assertEqual(after['completed']['older'],before['completed']['older'])
        self.assertEqual(after['network_retries'],[1,2,3]);self.assertTrue(after['terminal']);self.assertIsNone(after['active'])
        self.assertTrue(after['completed']['E3-C3-S9']['manual_completed']);self.assertEqual(after['victories'],2)
    def test_uncleared_wrong_stage_or_missing_attempt_is_rejected(self):
        with self.assertRaises(ValueError):manual_clear(self.state,self.node,'未通关蓝色当前节点','new.png','now')
        with self.assertRaises(ValueError):manual_clear(self.state,{**self.node,'key':'wrong'},'已通关绿色勾','new.png','now')
        self.state['attempted']={}
        with self.assertRaises(ValueError):manual_clear(self.state,self.node,'已通关绿色勾','new.png','now')
    def test_duplicate_reconciliation_is_rejected(self):
        self.state['completed'][self.node['key']]={}
        with self.assertRaises(ValueError):manual_clear(self.state,self.node,'已通关绿色勾','new.png','now')

if __name__=='__main__':unittest.main(verbosity=2)
