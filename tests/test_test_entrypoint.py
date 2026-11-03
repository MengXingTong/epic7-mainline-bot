"""离线测试入口回归；全部使用模拟依赖，不下载、不打包、不控制游戏。"""
import contextlib
import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

import run_offline_tests as entry


class TestEntrypointTests(unittest.TestCase):
    def test_vendor_is_available_before_discovery_and_paths_are_not_duplicated(self):
        root = str(entry.ROOT)
        vendor = str(entry.ROOT / 'vendor')
        with patch.object(sys, 'path', ['other', vendor, root, vendor]):
            entry.configure_paths()
            self.assertEqual(sys.path, [root, vendor, 'other'])
            entry.configure_paths()
            self.assertEqual(sys.path, [root, vendor, 'other'])

    def test_worker_dependencies_include_pillow_without_requiring_tk(self):
        with patch.object(entry.importlib, 'import_module') as load:
            entry.check_dependencies()
        names = [call.args[0] for call in load.call_args_list]
        self.assertIn('PIL.Image', names)
        self.assertIn('rapidocr_onnxruntime', names)
        self.assertNotIn('tkinter', names)

    def test_strict_gui_mode_imports_tk_pillow_tk_and_the_application(self):
        with patch.object(entry.importlib, 'import_module') as load:
            entry.check_dependencies(require_gui=True)
        names = [call.args[0] for call in load.call_args_list]
        for name in ('tkinter', 'PIL.ImageTk', 'assistant_app'):
            self.assertIn(name, names)

    def test_dependency_error_is_a_failure_not_a_skipped_suite(self):
        with patch.object(entry, 'configure_paths'), patch.object(entry, 'check_dependencies', side_effect=ModuleNotFoundError("missing", name='PIL')), patch.object(entry.unittest, 'main') as discover, contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(entry.main([]), 1)
            discover.assert_not_called()
            self.assertIn('依赖检查失败', output.getvalue())
            self.assertIn('PIL', output.getvalue())

    def test_main_honors_ci_gui_requirement_and_forwards_test_arguments(self):
        with patch.object(entry, 'configure_paths'), patch.object(entry, 'check_dependencies') as check, patch.dict(os.environ, {'EPIC7_REQUIRE_GUI_TESTS': '1'}), patch.object(entry.unittest, 'main', return_value=Mock(result=Mock(wasSuccessful=lambda: True))) as discover:
            self.assertEqual(entry.main(['-v', '-p', 'test_safety.py']), 0)
            check.assert_called_once_with(require_gui=True)
            args = discover.call_args.kwargs
            self.assertFalse(args['exit'])
            self.assertEqual(args['argv'][1:], ['discover', '-s', str(entry.ROOT / 'tests'), '-v', '-p', 'test_safety.py'])

    def test_failing_suite_returns_nonzero(self):
        with patch.object(entry, 'configure_paths'), patch.object(entry, 'check_dependencies'), patch.object(entry.unittest, 'main', return_value=Mock(result=Mock(wasSuccessful=lambda: False))):
            self.assertEqual(entry.main([]), 1)

    def test_isolated_source_checkout_loads_vendor_before_first_test(self):
        # 模拟首次安装后的源码目录；不依赖开发机已加载的 Pillow。
        with tempfile.TemporaryDirectory(prefix='epic7-ci-entry-') as folder:
            root = Path(folder)
            shutil.copy2(entry.ROOT / 'run_offline_tests.py', root)
            shutil.copy2(entry.ROOT / 'ui_text.py', root)
            vendor = root / 'vendor'
            (vendor / 'PIL').mkdir(parents=True)
            (vendor / 'PIL' / '__init__.py').write_text('', encoding='utf-8')
            (vendor / 'PIL' / 'Image.py').write_text('from_temporary_vendor = True', encoding='utf-8')
            for name in ('cv2', 'numpy', 'rapidocr_onnxruntime'):
                (vendor / (name + '.py')).write_text('', encoding='utf-8')
            (root / 'tests').mkdir()
            (root / 'tests' / 'test_first_import.py').write_text(
                'import unittest\nfrom PIL import Image\nclass FirstImport(unittest.TestCase):\n'
                '    def test_vendor(self):\n        self.assertTrue(Image.from_temporary_vendor)\n', encoding='utf-8')
            result = subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', str(root / 'run_offline_tests.py')],
                                    cwd=root, env={**os.environ, 'EPIC7_REQUIRE_GUI_TESTS': '0'},
                                    capture_output=True, text=True, encoding='utf-8', timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Ran 1 test', result.stderr)
            self.assertIn('OK', result.stderr)
