from pathlib import Path
import sys,importlib.util,json,types,tempfile,unittest
from unittest.mock import patch,Mock
qa=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('share_launcher',qa/'launcher.py');L=importlib.util.module_from_spec(spec);spec.loader.exec_module(L)
spec=importlib.util.spec_from_file_location('share_runner',qa/'runner.py');R=importlib.util.module_from_spec(spec);spec.loader.exec_module(R)
class LauncherTests(unittest.TestCase):
    def folder(self):
        temp=tempfile.TemporaryDirectory(prefix='epic7-离线测试-')
        self.addCleanup(temp.cleanup)
        return Path(temp.name)
    def test_stop_only_writes_marker(self):
        root=self.folder()
        with patch.object(L,'ROOT',root),patch.object(sys,'argv',['launcher.py','stop']),patch.object(L,'setup') as setup:
            self.assertEqual(L.main(),0);self.assertTrue((root/'STOP').exists());setup.assert_not_called()
    def test_terminal_start_cannot_silently_reset_history(self):
        root=self.folder();data={'terminal':True,'reason':'blocked','attempted':{'test':{'cost':8}}};(root/'state.json').write_text(json.dumps(data),encoding='utf8')
        with patch.object(L,'ROOT',root),patch.object(sys,'argv',['launcher.py','start']),patch.object(L,'preview') as preview:
            with self.assertRaises(RuntimeError):L.main()
            preview.assert_not_called();self.assertEqual(json.loads((root/'state.json').read_text()),data)
    def test_multiple_devices_are_blocked(self):
        root=self.folder();cfg={'adb':'','serial':'test-device','package':'test.game','strict_single_device':True}
        def fake_adb(c,*args):return 'List of devices attached\ntest-device\tdevice\nother-device\tdevice\n' if args[0]=='devices' else 'connected'
        with patch.object(L,'ROOT',root),patch.object(L,'load_config',return_value=cfg),patch.object(L,'find_adb',return_value=qa/'launcher.py'),patch.object(L,'adb',side_effect=fake_adb):
            with self.assertRaisesRegex(RuntimeError,'多个ADB设备'):L.setup()
    def test_wrong_foreground_is_blocked(self):
        root=self.folder();cfg={'adb':'','serial':'test-device','package':'test.game','strict_single_device':True}
        def fake_adb(c,*args):
            if args[0]=='devices':return 'List of devices attached\ntest-device\tdevice\n'
            if args[0]=='-s':return 'topResumedActivity=other.package/Activity'
            return 'connected'
        with patch.object(L,'ROOT',root),patch.object(L,'load_config',return_value=cfg),patch.object(L,'find_adb',return_value=qa/'launcher.py'),patch.object(L,'adb',side_effect=fake_adb):
            with self.assertRaisesRegex(RuntimeError,'前台包名'):L.setup()
    def resume_case(self,active,proof,mode='map'):
        root=self.folder();state={'terminal':True,'active':active,'attempted':{'stage-a':{'cost':8,'outcome':'defeat'}},'completed':{},'network_retries':[1,2,3]}
        (root/'state.json').write_text(json.dumps(state),encoding='utf8');(root/'STOP').write_text('user',encoding='utf8')
        class FakeRunner:
            def __init__(self):self.s=json.loads((root/'state.json').read_text(encoding='utf8'))
            def capture(self):return object()
            def map_ticket(self,f):return {'key':'stage-a'},[],proof
            def completed(self,why):self.s['completed']['stage-a']=self.s['active'].copy();self.s['active']=None
            def save(self):(root/'state.json').write_text(json.dumps(self.s),encoding='utf8')
        module=types.SimpleNamespace(Runner=FakeRunner,classify=lambda f:mode,event=Mock(),now=lambda:'test-time')
        return root,state,module
    def test_resume_without_green_proof_keeps_stop_and_history(self):
        root,state,module=self.resume_case({'key':'stage-a'},'未通关蓝色当前节点')
        with patch.object(L,'ROOT',root),patch.object(L,'setup'),patch.dict(sys.modules,{'runner':module}),patch('builtins.input',return_value='RESUME'),patch.object(L,'spawn_supervisor') as spawn:
            with self.assertRaisesRegex(RuntimeError,'绿色通关标记'):L.resume_checked()
            self.assertTrue((root/'STOP').exists());self.assertEqual(json.loads((root/'state.json').read_text()),state);spawn.assert_not_called()
    def test_manual_clear_resume_preserves_attempt_and_does_not_reenter(self):
        for answer in ('继续','RESUME'):
            with self.subTest(answer=answer):
                root,state,module=self.resume_case({'key':'stage-a'},'已通关绿色勾')
                with patch.object(L,'ROOT',root),patch.object(L,'setup'),patch.dict(sys.modules,{'runner':module}),patch('builtins.input',return_value=answer),patch.object(L,'spawn_supervisor') as spawn:
                    self.assertEqual(L.resume_checked(),0);after=json.loads((root/'state.json').read_text());self.assertFalse(after['terminal']);self.assertIsNone(after['active']);self.assertEqual(after['attempted']['stage-a']['cost'],8);self.assertEqual(after['attempted']['stage-a']['outcome'],'defeat');self.assertTrue(after['completed']['stage-a']['manual_completed']);self.assertEqual(after['network_retries'],[1,2,3]);spawn.assert_called_once()
    def test_network_resume_never_clears_retry_or_attempt_history(self):
        root,state,module=self.resume_case(None,'none',mode='lobby')
        with patch.object(L,'ROOT',root),patch.object(L,'setup'),patch.dict(sys.modules,{'runner':module}),patch('builtins.input',return_value='RESUME'),patch.object(L,'spawn_supervisor'):
            L.resume_checked();after=json.loads((root/'state.json').read_text());self.assertEqual(after['attempted'],state['attempted']);self.assertEqual(after['network_retries'],state['network_retries'])
    def test_unicode_path_capture_and_evidence(self):
        r=R.Runner.__new__(R.Runner);r.s={};image=R.np.zeros((900,1600,3),R.np.uint8);data=R.cv2.imencode('.png',image)[1].tobytes();r.adb=lambda *a:data;r.ocr=lambda im:([],None)
        root=self.folder()
        with patch.object(R,'ROOT',root):
            f=r.capture();self.assertEqual(f.image.shape,(900,1600,3));path=r.evidence('unicode-qa');self.assertTrue((root/path).is_file());self.assertTrue((root/'latest.png').is_file())
    def test_non_16_9_capture_is_rejected_before_input(self):
        r=R.Runner.__new__(R.Runner);r.s={};data=R.cv2.imencode('.png',R.np.zeros((1000,1500,3),R.np.uint8))[1].tobytes();r.adb=lambda *a:data;r.ocr=Mock()
        with self.assertRaisesRegex(RuntimeError,'16:9'):r.capture()
        r.ocr.assert_not_called()
if __name__=='__main__':unittest.main(verbosity=2)
