"""No OS input. Default GUI worker must not navigate to account settings."""
import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from PIL import Image
from assistant_worker import prepare_selected_profile

class DirectStartTests(unittest.TestCase):
    def test_existing_profile_is_read_in_place_without_account_ocr(self):
        root=Path('existing-profile');state={'attempted':{},'completed':{}}
        with patch('assistant_config.history_gate',return_value=(root,state)),patch('pc_quickstart.inspect_account',side_effect=AssertionError('No account OCR')):
            self.assertEqual(prepare_selected_profile({'settings':{'data_dir':str(root)}},Mock()),root)
    def test_first_start_verifies_lobby_only_and_never_opens_settings(self):
        with tempfile.TemporaryDirectory() as d:
            home=Path(d).resolve();root=home/'profile'
            transport=Mock();transport.capture.return_value=SimpleNamespace(image=Image.new('RGB',(800,450)))
            ocr=Mock(return_value=([],None));ctl=Mock()
            request={'settings':{},'target':{'client':'pc'},'user_selected_profile':True,'run_dir':d,'run_id':'test'}
            with patch('assistant_config.HOME',home),patch('assistant_portable.registered_root',return_value=None),patch('assistant_portable.initialize_selected',return_value=(root,{})) as initialize,patch('assistant_transport.UnifiedTransport',return_value=transport),patch('rapidocr_onnxruntime.RapidOCR',return_value=ocr),patch('runner.classify',return_value='lobby'),patch('pc_quickstart.inspect_account',side_effect=AssertionError('No account navigation')):
                result=prepare_selected_profile(request,ctl)
            self.assertEqual(result,root);initialize.assert_called_once_with(True)
            self.assertEqual([c[0] for c in transport.method_calls],['capture','ensure'])
    def test_unknown_first_frame_does_not_initialize_or_click(self):
        with tempfile.TemporaryDirectory() as d:
            transport=Mock();transport.capture.return_value=SimpleNamespace(image=Image.new('RGB',(800,450)))
            request={'settings':{},'target':{'client':'pc'},'user_selected_profile':True,'run_dir':d,'run_id':'test'}
            with patch('assistant_config.HOME',Path(d)),patch('assistant_portable.registered_root',return_value=None),patch('assistant_portable.initialize_selected') as initialize,patch('assistant_transport.UnifiedTransport',return_value=transport),patch('rapidocr_onnxruntime.RapidOCR',return_value=Mock(return_value=([],None))),patch('runner.classify',return_value='unknown'):
                with self.assertRaises(RuntimeError):prepare_selected_profile(request,Mock())
            initialize.assert_not_called();transport.tap.assert_not_called()
    def test_foreground_mode_is_rejected_before_any_native_api(self):
        from assistant_transport import UnifiedTransport
        from pc_backend import PcSafetyError
        with patch('pc_backend.Win32Api',side_effect=AssertionError('Foreground must never initialize')):
            with self.assertRaises(PcSafetyError):UnifiedTransport({'pc_input':'foreground'},{'client':'pc'})
