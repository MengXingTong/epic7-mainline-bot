"""Report contention must not break progress; progress contention must stop input."""
import copy,ctypes,json,os,sys,tempfile,time,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner

@contextmanager
def deny_replace(path):
    """Real Windows shared handle allowing reads/writes, but not replacement/deletion."""
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    kernel.CreateFileW.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
    handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0x80,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:yield
    finally:kernel.CloseHandle(handle)

class StatusReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.r=runner.Runner.__new__(runner.Runner)
        self.r.s={'attempted':{'S1':{'outcome':'pending'}},'completed':{'S0':{}},'active':{'key':'S1'},'victories':1,'last_cleared':{'key':'S0'}}
        self.r.ticket=None;self.r.pc=Mock();self.r.ensure_game=Mock()
        self.r.frame=runner.Frame(runner.np.zeros((900,1600,3),runner.np.uint8),[])
        self.patch=patch.object(runner,'ROOT',self.root);self.patch.start()
    def tearDown(self):self.patch.stop();self.temp.cleanup()
    def test_success_writes_report_and_keeps_durable_history(self):
        original=copy.deepcopy(self.r.s);self.r.save()
        saved=json.loads((self.root/'state.json').read_text(encoding='utf-8'))
        for key in ('attempted','completed','active','last_cleared'):self.assertEqual(saved[key],original[key])
        self.assertEqual(self.r.report_warning,'')
        self.assertIn('S1',(self.root/'STATUS.md').read_text(encoding='utf-8'))
        self.assertEqual(list(self.root.glob('.STATUS-*.tmp')),[])
    def test_warning_only_logged_on_failure_and_recovery_transitions(self):
        with patch('runner.write_status_report',side_effect=['warning','warning','']),patch('builtins.print') as output:
            self.r.save();self.r.save();self.r.save()
        self.assertEqual(output.call_count,2);self.assertEqual(self.r.report_warning,'')
    def test_report_temp_creation_error_is_nonfatal(self):
        with patch('runner.tempfile.NamedTemporaryFile',side_effect=PermissionError(13,'denied')):
            self.r.save()
        self.assertTrue((self.root/'state.json').exists());self.assertIn('状态报告',self.r.report_warning)
    def test_helper_refuses_state_or_other_critical_targets(self):
        for name in ('state.json','events.jsonl','evidence.png'):
            with self.assertRaises(ValueError):runner.write_status_report(self.root/name,'must not write')
        self.assertEqual(list(self.root.iterdir()),[])
    def test_critical_state_error_propagates_and_prevents_click(self):
        with patch('runner.atomic_json',side_effect=PermissionError(13,'state denied')),patch('runner.write_status_report') as report:
            with self.assertRaises(PermissionError):self.r.action('test',xy=(800,450))
        self.r.pc.tap.assert_not_called();report.assert_not_called()
    def test_fatal_worker_error_clears_prior_noncritical_report_warning(self):
        from assistant_worker import Control
        request={'run_dir':str(self.root),'run_id':'test','settings':{'task':'mainline'},'target':{'client':'pc'}}
        control=Control(request)
        with patch('builtins.print'):
            control.status('battle',mode='run',warning='report unavailable')
            control.status('state.json write denied',mode='blocked')
        self.assertEqual(control.last['mode'],'blocked');self.assertEqual(control.last['warning'],'')
    @unittest.skipUnless(os.name=='nt','Real Windows file sharing test')
    def test_real_locked_report_does_not_block_save_and_recovers(self):
        report=self.root/'STATUS.md';report.write_text('original report',encoding='utf-8')
        original=copy.deepcopy(self.r.s)
        with deny_replace(report):
            self.r.save()
            self.assertIn('状态报告',self.r.report_warning)
            self.assertEqual(report.read_text(encoding='utf-8'),'original report')
            saved=json.loads((self.root/'state.json').read_text(encoding='utf-8'))
            for key in ('attempted','completed','active','last_cleared'):self.assertEqual(saved[key],original[key])
            self.assertEqual(list(self.root.glob('.STATUS-*.tmp')),[])
        self.r.save();self.assertEqual(self.r.report_warning,'');self.assertIn('S1',report.read_text(encoding='utf-8'))
    @unittest.skipUnless(os.name=='nt','Real Windows file sharing test')
    def test_real_locked_report_allows_one_planned_fake_input_only(self):
        report=self.root/'STATUS.md';report.write_text('old report',encoding='utf-8')
        with deny_replace(report):self.r.action('test planned action',xy=(800,450))
        self.r.pc.tap.assert_called_once_with(800,450)
        self.assertIn('S1',json.loads((self.root/'state.json').read_text(encoding='utf-8'))['attempted'])
    @unittest.skipUnless(os.name=='nt','Real Windows file sharing test')
    def test_real_locked_state_never_allows_input(self):
        self.r.save();state=self.root/'state.json';before=state.read_bytes()
        with deny_replace(state),self.assertRaises(PermissionError):self.r.action('should not execute',xy=(800,450))
        self.assertEqual(state.read_bytes(),before);self.r.pc.tap.assert_not_called()
