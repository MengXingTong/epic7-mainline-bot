"""Latest display contention preserves a fresh immutable pair before continuing."""
import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import runner
from test_status_report import deny_replace

class CaptureDisplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.bytes=b'current synthetic image bytes';self.ocr=dict(time='now',words=[],text='new OCR')
    def tearDown(self):self.temp.cleanup()
    def write(self):return runner.write_capture_display(self.root,self.bytes,self.ocr)
    def assert_clean(self):self.assertEqual(list(self.root.glob('.capture-*')),[])
    def test_success_writes_current_display_copies_without_extra_evidence(self):
        warning,proof=self.write();self.assertEqual(warning,'');self.assertIsNone(proof)
        self.assertEqual((self.root/'latest.png').read_bytes(),self.bytes)
        self.assertEqual(json.loads((self.root/'latest-ocr.json').read_text()),self.ocr);self.assert_clean()
    def test_display_replace_failure_preserves_fresh_pair_and_critical_records(self):
        (self.root/'latest.png').write_bytes(b'old image');(self.root/'latest.tmp.png').write_bytes(b'untouched old temp')
        for name in ('state.json','entry-intent.json','events.jsonl'):(self.root/name).write_bytes(b'original')
        with patch('runner.os.replace',side_effect=PermissionError(13,'denied')):warning,proof=self.write()
        self.assertIn('独立留证',warning);self.assertEqual((self.root/proof['image']).read_bytes(),self.bytes)
        self.assertEqual(json.loads((self.root/proof['ocr']).read_text()),self.ocr)
        for name in ('state.json','entry-intent.json','events.jsonl'):self.assertEqual((self.root/name).read_bytes(),b'original')
        self.assertEqual((self.root/'latest.tmp.png').read_bytes(),b'untouched old temp');self.assert_clean()
    def test_second_display_replace_failure_still_saves_one_matching_pair(self):
        original=runner.os.replace
        def replace(source,target):
            if Path(target).name=='latest-ocr.json':raise PermissionError(13,'locked OCR display')
            return original(source,target)
        with patch('runner.os.replace',side_effect=replace):warning,proof=self.write()
        self.assertTrue(warning);self.assertEqual((self.root/proof['image']).read_bytes(),self.bytes)
        self.assertEqual(json.loads((self.root/proof['ocr']).read_text()),self.ocr);self.assert_clean()
    def test_repeated_failures_create_distinct_immutable_evidence_then_recover(self):
        with patch('runner.os.replace',side_effect=PermissionError(13,'denied')):
            a=self.write()[1];b=self.write()[1]
        self.assertNotEqual(a['image'],b['image']);self.assertTrue((self.root/a['ocr']).exists())
        self.assertEqual(self.write(),('',None));self.assert_clean()
    def test_temporary_write_failure_remains_fatal(self):
        with patch('runner.tempfile.NamedTemporaryFile',side_effect=OSError('full disk')):
            with self.assertRaises(OSError):self.write()
        self.assertFalse((self.root/'evidence').exists())
    def test_fallback_evidence_write_failure_remains_fatal(self):
        real_open=Path.open
        def open_path(path,*a,**kw):
            if path.parent.name=='evidence':raise OSError('critical evidence denied')
            return real_open(path,*a,**kw)
        with patch('runner.os.replace',side_effect=PermissionError(13,'display locked')),patch.object(Path,'open',open_path):
            with self.assertRaises(OSError):self.write()
        self.assert_clean()
    def test_fallback_ocr_write_failure_remains_fatal(self):
        real_open=Path.open
        def open_path(path,*a,**kw):
            if path.parent.name=='evidence' and path.suffix=='.json':raise OSError('critical OCR denied')
            return real_open(path,*a,**kw)
        with patch('runner.os.replace',side_effect=PermissionError(13,'display locked')),patch.object(Path,'open',open_path):
            with self.assertRaises(OSError):self.write()
        self.assert_clean()
    @unittest.skipUnless(os.name=='nt','Real Windows file sharing')
    def test_real_locked_display_saves_evidence_and_later_updates(self):
        target=self.root/'latest.png';target.write_bytes(b'old')
        with deny_replace(target):
            warning,proof=self.write();self.assertTrue(warning)
            self.assertEqual(target.read_bytes(),b'old');self.assertEqual((self.root/proof['image']).read_bytes(),self.bytes)
        self.assertEqual(self.write(),('',None));self.assertEqual(target.read_bytes(),self.bytes)
    def make_runner(self):
        r=runner.Runner.__new__(runner.Runner);r._capture_pixels=Mock(return_value=(runner.np.full((900,1600,3),22,runner.np.uint8),(1600,900)))
        r.ocr=Mock(return_value=([],None));r.s=dict(attempted={'old':{'keep':True}},completed={},active=None)
        return r
    def test_capture_uses_fresh_memory_frame_not_locked_display_and_logs_provenance(self):
        r=self.make_runner();old=copy.deepcopy(r.s)
        with patch.object(runner,'ROOT',self.root),patch('runner.os.replace',side_effect=PermissionError(13,'display locked')),patch('builtins.print'):
            current=r.capture()
        self.assertIs(r.frame,current);self.assertEqual(r.s,old);self.assertTrue(r.capture_snapshot)
        self.assertIn('capture_display_fallback',(self.root/'events.jsonl').read_text(encoding='utf-8'))
    def test_capture_evidence_or_event_failure_never_returns_usable_frame(self):
        r=self.make_runner()
        with patch.object(runner,'ROOT',self.root),patch('runner.os.replace',side_effect=PermissionError(13,'display locked')),patch('runner.event',side_effect=OSError('event log denied')):
            with self.assertRaises(OSError):r.capture()
    def test_capture_encode_error_is_not_ignored(self):
        r=self.make_runner()
        with patch.object(runner,'ROOT',self.root),patch('runner.cv2.imencode',return_value=(False,None)):
            with self.assertRaises(OSError):r.capture()
        self.assertFalse((self.root/'latest.png').exists())
if __name__=='__main__':unittest.main()
