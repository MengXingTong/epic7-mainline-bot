"""Manual-clear recovery regressions. Temp histories and fakes only, no native input."""
import copy,json,sys,tempfile,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from mainline_reconcile import ReconcileBlocked,pending_reconciliation,match_account,exact_map_proof,reconcile_live,chapter_back_target
from assistant_config import validate_run
import runner

KEY='E1-C1-S1'
def history():
    active=dict(key=KEY,episode=1,chapter=1,stage=1,name='测试关',outcome='defeat')
    return dict(attempted={KEY:copy.deepcopy(active)},completed={},active=active,terminal=True,status='original failure',reason='original reason',stop_evidence='evidence/original.png',failed_stage=copy.deepcopy(active),pc_profile_binding={'server':'测试服务器','account_id':'1111'})
def account():return dict(server='测试服务器',account_id='1111',checked_at=time.time(),window={'hwnd':10,'pid':20,'created':30})
def sample_frame(at=None):
    f=runner.Frame(np.zeros((900,1600,3),np.uint8),[]);f.at=time.time()-.1 if at is None else at;return f

class RecoveryPolicyTests(unittest.TestCase):
    def test_only_exact_durable_pending_stage_can_be_verified(self):self.assertTrue(pending_reconciliation(history()))
    def test_missing_attempt_not_verifiable(self):
        s=history();s['attempted']={};self.assertFalse(pending_reconciliation(s))
    def test_conflicting_attempt_metadata_blocked(self):
        s=history();s['attempted'][KEY]['stage']=2;self.assertFalse(pending_reconciliation(s))
    def test_duplicate_completed_not_reconciled(self):
        s=history();s['completed'][KEY]={};self.assertFalse(pending_reconciliation(s))
    def test_unknown_legacy_key_is_not_silently_repaired(self):
        s=history();s['active']['key']='S1';self.assertFalse(pending_reconciliation(s))
    def test_same_account_required(self):
        p=account();p['account_id']='2222'
        with self.assertRaises(ReconcileBlocked):match_account(history(),p)
    def test_expired_account_proof_blocked(self):
        p=account();p['checked_at']-=121
        with self.assertRaises(ReconcileBlocked):match_account(history(),p)
    def test_missing_window_proof_blocked(self):
        p=account();p.pop('window')
        with self.assertRaises(ReconcileBlocked):match_account(history(),p)
    def test_unbound_history_not_auto_adopted(self):
        s=history();s.pop('pc_profile_binding')
        with self.assertRaises(ReconcileBlocked):match_account(s,account())
    def test_initial_association_needs_explicit_consent_and_expected_server(self):
        s=history();s.pop('pc_profile_binding')
        self.assertEqual(match_account(s,account(),True,'测试服务器')['account_id'],'1111')
        with self.assertRaises(ReconcileBlocked):match_account(s,account(),True,'其他服务器')
    def test_verification_mode_does_not_release_entry_gate(self):
        from assistant_config import gate_mainline
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);s=history();(p/'state.json').write_text(json.dumps(s),encoding='utf-8')
            cfg=dict(data_dir=d,task='mainline',observe=False,limit=1,pc_input='messages')
            _,read=validate_run(cfg,{'client':'pc'},allow_reconcile=True)
            self.assertEqual(read,s)
            with self.assertRaises(ValueError):gate_mainline(read)
            with self.assertRaises(ValueError):validate_run(cfg,{'client':'pc'})
    def test_stop_marker_never_auto_removed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'state.json').write_text(json.dumps(history()),encoding='utf-8');(p/'STOP').write_text('user stop')
            with self.assertRaises(ValueError):validate_run(dict(data_dir=d,task='mainline',observe=False,limit=1,pc_input='messages'),{'client':'pc'},allow_reconcile=True)
            self.assertTrue((p/'STOP').exists())

class RecoveryTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.state=history()
        (self.root/'state.json').write_text(json.dumps(self.state),encoding='utf-8');self.original=(self.root/'state.json').read_bytes()
        self.frames=[sample_frame(time.time()-.2),sample_frame(time.time()-.1)]
        self.node={k:self.state['active'][k] for k in ('key','episode','chapter','stage','name')}
    def tearDown(self):self.temp.cleanup()
    def run_ok(self,proofs=None,capture=None,tap=None,guard=None):
        proofs=proofs or [(self.node,'已通关绿色勾',None)]*2
        with patch('runner.classify',return_value='map'),patch('runner.resource_warning',return_value=False),patch('mainline_reconcile.exact_map_proof',side_effect=proofs):
            return reconcile_live(self.root,self.state,account(),capture or Mock(side_effect=self.frames),tap or Mock(),guard or Mock(),private_dir=self.root/'private')
    def test_exact_green_is_copy_on_write_and_keeps_original_failure(self):
        guard=Mock();tap=Mock();new=self.run_ok(tap=tap,guard=guard)
        self.assertEqual(self.state,history());self.assertIsNone(new['active']);self.assertFalse(new['terminal'])
        self.assertTrue(new['completed'][KEY]['manual_completed']);self.assertEqual(new['attempted'][KEY]['outcome'],'defeat')
        self.assertEqual(new['stop_evidence'],self.state['stop_evidence']);self.assertEqual(new['failed_stage'],self.state['failed_stage'])
        self.assertEqual(new['manual_clears'],1);self.assertEqual(new['script_victories'],0)
        self.assertTrue((self.root/new['completed'][KEY]['evidence']).is_file());self.assertTrue(list((self.root/'private').glob('history-before-*.json')))
        tap.assert_not_called();guard.assert_called_once()
    def test_selected_profile_recovery_never_reads_or_adds_account_binding(self):
        self.state.pop('pc_profile_binding');(self.root/'state.json').write_text(json.dumps(self.state),encoding='utf-8')
        proofs=[(self.node,'已通关绿色勾',None)]*2
        with patch('runner.classify',return_value='map'),patch('runner.resource_warning',return_value=False),patch('mainline_reconcile.exact_map_proof',side_effect=proofs),patch('mainline_reconcile.match_account',side_effect=AssertionError('No account check')):
            new=reconcile_live(self.root,self.state,None,Mock(side_effect=self.frames),Mock(),Mock(),private_dir=self.root/'private',selected_profile=True)
        self.assertNotIn('pc_profile_binding',new)
        self.assertEqual(new['attempted'][KEY]['outcome'],'defeat')
        self.assertTrue(new['completed'][KEY]['manual_completed'])
        self.assertEqual(new['reconciliation_history'][-1]['verification'],'selected_local_profile')
    def test_report_failure_does_not_undo_persisted_manual_clear(self):
        with patch('runner.write_status_report',return_value='report temporarily unavailable'):
            new=self.run_ok()
        self.assertEqual(json.loads((self.root/'state.json').read_text(encoding='utf-8')),new)
        self.assertTrue(new['completed'][KEY]['manual_completed'])
        self.assertEqual(new['attempted'][KEY]['outcome'],'defeat')
    def test_confirm_must_be_a_separate_fresh_frame(self):
        self.frames[1].at=self.frames[0].at
        with self.assertRaises(ReconcileBlocked):self.run_ok()
        self.assertEqual((self.root/'state.json').read_bytes(),self.original)
    def test_mismatching_confirm_does_not_clear_record(self):
        with self.assertRaises(ReconcileBlocked):self.run_ok(proofs=[(self.node,'已通关绿色勾',None),(None,None,(100,200))])
        self.assertEqual((self.root/'state.json').read_bytes(),self.original)
    def test_resource_popup_has_zero_navigation_and_zero_write(self):
        tap=Mock()
        with patch('runner.resource_warning',return_value=True):
            with self.assertRaises(ReconcileBlocked):reconcile_live(self.root,self.state,account(),Mock(return_value=self.frames[0]),tap,Mock())
        tap.assert_not_called();self.assertEqual((self.root/'state.json').read_bytes(),self.original)
    def test_history_cas_prevents_overwrite(self):
        newer=copy.deepcopy(self.state);newer['external_change']=True
        def capture():
            (self.root/'state.json').write_text(json.dumps(newer),encoding='utf-8');return self.frames.pop(0)
        with self.assertRaises(ReconcileBlocked):self.run_ok(capture=capture)
        self.assertTrue(json.loads((self.root/'state.json').read_text())['external_change'])
    def test_game_guard_failure_keeps_history(self):
        with self.assertRaises(RuntimeError):self.run_ok(guard=Mock(side_effect=RuntimeError('window changed')))
        self.assertEqual((self.root/'state.json').read_bytes(),self.original)
    def test_unsettled_battle_never_gets_navigation(self):
        tap=Mock()
        with patch('runner.classify',return_value='battle'),patch('runner.resource_warning',return_value=False):
            with self.assertRaises(ReconcileBlocked):reconcile_live(self.root,self.state,account(),Mock(return_value=self.frames[0]),tap,Mock())
        tap.assert_not_called();self.assertEqual((self.root/'state.json').read_bytes(),self.original)

class ChapterChevronTests(unittest.TestCase):
    def frame(self,ch=2):
        rows=[([[80,20],[220,20],[220,50],[80,50]],'Episode 1',.99),([[110,120],[250,120],[250,145],[110,145]],f'第{ch}章 测试',.99),([[1350,800],[1520,800],[1520,850],[1350,850]],'准备战斗',.99)]
        return runner.Frame(np.zeros((900,1600,3),np.uint8),rows)
    def test_next_chapter_without_chevron_is_not_blindly_clicked(self):
        with self.assertRaises(ReconcileBlocked):chapter_back_target(self.frame(),{'episode':1,'chapter':1})
    def test_positive_chevron_geometry(self):
        import cv2
        f=self.frame();cv2.polylines(f.image,[np.array([[67,126],[57,137],[67,148]],np.int32)],False,(200,200,200),3)
        kind,xy=chapter_back_target(f,{'episode':1,'chapter':1})
        self.assertEqual(kind,'previous_chapter:2');self.assertTrue(50<xy[0]<75 and 120<xy[1]<155)
    def test_other_episode_never_navigated(self):self.assertIsNone(chapter_back_target(self.frame(),{'episode':2,'chapter':1}))
    def test_current_chapter_does_not_go_back(self):self.assertIsNone(chapter_back_target(self.frame(1),{'episode':1,'chapter':1}))

class SelectedTargetStartupRegression(unittest.TestCase):
    def test_pc_start_skips_account_ocr_and_pins_selected_target(self):
        from assistant_worker import mainline_run
        from pc_backend import WindowSnapshot
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);s=history();s.update(active=None,terminal=False);(p/'state.json').write_text(json.dumps(s),encoding='utf-8');(p/'config.json').write_text('{}')
            window=WindowSnapshot(10,20,'EpicSeven.exe',30,0,0,1600,900)
            proof=account();proof['window']=window.identity()
            class FakeRunner:
                def __init__(self,observe):self.s=copy.deepcopy(s)
                def capture(self):return sample_frame()
            class FakeBackend:
                def __init__(inner,*args,**kwargs):inner.window=window
                def snapshot(inner):return window
                def authorize_selected_target(inner,value):self.assertEqual(value,window.identity())
            settings=dict(data_dir=d,task='mainline',observe=False,limit=1,pc_input='messages')
            target=dict(client='pc',exe='EpicSeven.exe',title='第七史诗',hwnd=10,pid=20,created=30)
            ctl=Mock()
            with patch('runner.Runner',FakeRunner),patch('runner.classify',return_value='map'),patch('pc_backend.PcBackend',FakeBackend),patch('pc_message_backend.MessageWin32Api',return_value=Mock()),patch('pc_quickstart.inspect_account',side_effect=AssertionError('Account OCR must not run')),patch('pc_quickstart.return_to_game'),patch.dict('os.environ',{},clear=False):
                mainline_run(dict(settings=settings,target=target,run_dir=d,preflight_only=True),ctl)
            self.assertEqual(ctl.status.call_args.kwargs['mode'],'done')


    def test_pending_recovery_runs_before_stage_entry_gate(self):
        from assistant_worker import mainline_run
        from pc_backend import WindowSnapshot
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);s=history();recovered=copy.deepcopy(s);recovered.update(active=None,terminal=False);recovered['completed'][KEY]={'manual_completed':True};(p/'state.json').write_text(json.dumps(s),encoding='utf-8');(p/'config.json').write_text('{}')
            window=WindowSnapshot(10,20,'EpicSeven.exe',30,0,0,1600,900)
            proof=account();proof['window']=window.identity()
            class FakeRunner:
                def __init__(self,observe):self.s=copy.deepcopy(s)
                def capture(self):return sample_frame()
            class FakeBackend:
                def __init__(inner,*args,**kwargs):inner.window=window
                def snapshot(inner):return window
                def tap(inner,*args):raise AssertionError('No entry input belongs in this test')
                def ensure(inner):return window
                def authorize_selected_target(inner,value):self.assertEqual(value,window.identity())
            settings=dict(data_dir=d,task='mainline',observe=False,limit=1,pc_input='messages')
            target=dict(client='pc',exe='EpicSeven.exe',title='第七史诗',hwnd=10,pid=20,created=30)
            ctl=Mock()
            with patch('mainline_reconcile.reconcile_live',return_value=recovered) as recovery,patch('runner.Runner',FakeRunner),patch('runner.classify',return_value='map'),patch('pc_backend.PcBackend',FakeBackend),patch('pc_message_backend.MessageWin32Api',return_value=Mock()),patch('pc_quickstart.inspect_account',side_effect=AssertionError('Account OCR must not run')),patch('pc_quickstart.return_to_game'),patch.dict('os.environ',{},clear=False):
                mainline_run(dict(settings=settings,target=target,run_dir=d,preflight_only=True),ctl)
            self.assertEqual(ctl.status.call_args.kwargs['mode'],'done')
            recovery.assert_called_once();self.assertEqual(recovery.call_args.args[1]['active']['key'],KEY)
            self.assertIsNone(recovery.call_args.args[2]);self.assertTrue(recovery.call_args.kwargs['selected_profile'])

class AdbAccountAdapterTests(unittest.TestCase):
    def make(self):
        from assistant_transport import AdbNavigationBackend,FrameSnapshot
        from PIL import Image
        adapter=AdbNavigationBackend.__new__(AdbNavigationBackend)
        adapter.transport=Mock();adapter.latest=FrameSnapshot(Image.new('RGB',(800,450)),'fake',time.monotonic())
        adapter.window=SimpleNamespace(identity=lambda:{'client':'mumu','serial':'fake-device','package':'example.game'})
        adapter.allowed=False;adapter.digest=b'expected';return adapter
    def test_unverified_account_cannot_tap(self):
        a=self.make()
        with self.assertRaises(RuntimeError):a.tap(800,450)
        a.transport.tap.assert_not_called()
    def test_wrong_device_proof_rejected(self):
        a=self.make()
        with self.assertRaises(RuntimeError):a.authorize({'window':{'client':'other'},'checked_at':time.time()})
        self.assertFalse(a.allowed)
    def test_tap_uses_device_coordinates_not_desktop_cursor(self):
        a=self.make();a.allowed=True;a.tap(800,450)
        snapshot,token=a.transport.tap.call_args.args;self.assertIs(snapshot,a.latest);self.assertEqual(token.center,(400,225))
    def test_startup_observation_digest_is_required(self):
        a=self.make()
        with self.assertRaises(RuntimeError):a.navigate_account(sample_frame())
        a.transport.tap.assert_not_called()
    def test_back_consumes_frame_and_uses_android_back_only(self):
        a=self.make();a.allowed=True;a.back()
        a.transport._fresh.assert_called_once_with(a.latest);self.assertIsNone(a.transport.frame)
        a.transport.adb.assert_called_once_with('shell','input','keyevent','4')


class DamagedRecordTests(unittest.TestCase):
    def test_malformed_attempt_is_not_silently_repaired(self):
        s=history();s['attempted'][KEY]=None;self.assertFalse(pending_reconciliation(s))
