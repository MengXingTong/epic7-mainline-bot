"""GUI thumbnail contention is noncritical; history/status/Stop errors are not."""
import ctypes,json,os,sys,tempfile,unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from assistant_worker import Control,StopRun


@contextmanager
def deny_preview_replace(path):
    from ctypes import wintypes as w
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    kernel.CreateFileW.restype=w.HANDLE
    kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
    handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0x80,None)
    if handle==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
    try:yield
    finally:kernel.CloseHandle(handle)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.control=Control(dict(run_dir=str(self.root),run_id='known',settings=dict(task='mainline'),target=dict(client='pc')))
        self.image=Image.new('RGB',(1600,900),'red')
        self.output=patch('builtins.print');self.output.start()
    def tearDown(self):self.output.stop();self.temp.cleanup()
    def status(self,**values):
        self.control.status('fresh business state',mode='run',**values)
        return json.loads((self.root/'status.json').read_text(encoding='utf-8'))
    def assert_clean(self):self.assertEqual(list(self.root.glob('.preview-*.png')),[])
    def test_atomic_success_with_bounded_copy_and_no_leftover_temp(self):
        self.assertTrue(self.control.preview(self.image))
        with Image.open(self.root/'preview.png') as result:
            self.assertEqual(result.size,(560,315));self.assertEqual(result.getpixel((0,0)),(255,0,0))
        self.assertEqual(self.image.size,(1600,900));self.assert_clean()
    def test_replace_permission_error_keeps_old_preview_and_protected_records(self):
        self.control.preview(self.image);old=(self.root/'preview.png').read_bytes()
        records={name:b'preserved original bytes' for name in ('state.json','events.jsonl','entry-intent.json','evidence.png','preview.tmp.png')}
        for name,value in records.items():(self.root/name).write_bytes(value)
        with patch('assistant_worker.os.replace',side_effect=PermissionError(13,'denied')):
            self.assertFalse(self.control.preview(Image.new('RGB',(1600,900),'blue')))
        self.assertIn('预览暂时无法更新',self.control.preview_warning)
        self.assertEqual((self.root/'preview.png').read_bytes(),old)
        for name,value in records.items():self.assertEqual((self.root/name).read_bytes(),value)
        self.assert_clean()
    def test_temp_creation_and_image_save_errors_only_degrade_preview(self):
        for target in ('assistant_worker.tempfile.NamedTemporaryFile','PIL.Image.Image.save'):
            with self.subTest(target=target),patch(target,side_effect=PermissionError(13,'denied')):
                self.assertFalse(self.control.preview(self.image))
            self.assert_clean()
        self.assertFalse((self.root/'preview.png').exists())
        self.assertTrue(self.control.preview(self.image));self.assertEqual(self.control.preview_warning,'')
    def test_repeated_failures_log_once_and_later_capture_recovers(self):
        with patch.object(self.control,'log') as log:
            with patch('assistant_worker.os.replace',side_effect=PermissionError(13,'denied')):
                self.control.preview(self.image);self.control.preview(self.image)
            self.assertEqual(log.call_count,1)
            self.assertIn('预览暂时无法更新',self.status()['warning'])
            self.control.preview(self.image);self.control.preview(self.image)
            self.assertEqual(log.call_count,2);self.assertIn('恢复',log.call_args.args[0])
            self.assertEqual(self.status().get('warning',''),'')
    def test_preview_warning_composes_with_business_warning_without_sticking(self):
        with patch('assistant_worker.os.replace',side_effect=PermissionError(13,'denied')):self.control.preview(self.image)
        shown=self.status(warning='状态报告警告')
        self.assertIn('状态报告警告',shown['warning']);self.assertIn('预览',shown['warning'])
        self.assertEqual(self.control.last['warning'],'状态报告警告')
        self.control.preview(self.image)
        self.assertEqual(self.status()['warning'],'状态报告警告')
    def test_blocked_error_wins_over_old_display_warnings(self):
        with patch('assistant_worker.os.replace',side_effect=PermissionError(13,'denied')):self.control.preview(self.image)
        self.control.status('state write denied',mode='blocked')
        shown=json.loads((self.root/'status.json').read_text(encoding='utf-8'))
        self.assertEqual(shown['warning'],'');self.assertEqual(shown['mode'],'blocked')
        self.assertEqual(shown['status'],'state write denied')
    def test_status_persistence_error_still_propagates(self):
        with patch('assistant_worker.atomic_json',side_effect=PermissionError(13,'state denied')):
            with self.assertRaises(PermissionError):self.status()
    def test_stop_command_still_wins_after_failed_preview(self):
        (self.root/'control.json').write_text(json.dumps(dict(run_id='known',action='stop')),encoding='utf-8')
        with patch('assistant_worker.os.replace',side_effect=PermissionError(13,'denied')):self.control.preview(self.image)
        with self.assertRaises(StopRun):self.control.check()
    def test_non_io_programming_errors_not_hidden(self):
        with patch('PIL.Image.Image.save',side_effect=ValueError('invalid image')):
            with self.assertRaises(ValueError):self.control.preview(self.image)
        self.assert_clean()
    @unittest.skipUnless(os.name=='nt','Real Windows sharing test')
    def test_real_windows_shared_handle_keeps_worker_status_and_recovers(self):
        self.control.preview(self.image);path=self.root/'preview.png';before=path.read_bytes()
        with deny_preview_replace(path):
            self.assertFalse(self.control.preview(Image.new('RGB',(1600,900),'blue')))
            self.assertEqual(path.read_bytes(),before)
            self.assertIn('预览',self.status()['warning']);self.assert_clean()
        self.assertTrue(self.control.preview(Image.new('RGB',(1600,900),'blue')))
        with Image.open(path) as result:self.assertEqual(result.getpixel((0,0)),(0,0,255))
        self.assertEqual(self.status().get('warning',''),'');self.assert_clean()

if __name__=='__main__':unittest.main()
