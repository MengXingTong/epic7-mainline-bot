"""安装器回归：替换全部下载调用，不联网，不安装或修改全局代理。"""
import contextlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


class DependencyInstallerTests(unittest.TestCase):
    def run_installer(self, results):
        environment = {'HTTP_PROXY': 'http://example.invalid:8080',
                       'https_proxy': 'http://example.invalid:8080',
                       'ALL_PROXY': 'http://example.invalid:8080', 'KEEP': 'original'}
        with patch.dict(os.environ, environment, clear=True), patch.object(sys, 'version_info', (3, 12)), patch('subprocess.run', side_effect=[Mock(returncode=code) for code in results]) as download, contextlib.redirect_stdout(io.StringIO()):
            original = dict(os.environ)
            with self.assertRaises(SystemExit) as result:
                runpy.run_path(str(ROOT / 'install_dependencies.py'), run_name='__main__')
            self.assertEqual(dict(os.environ), original)
        return download.call_args_list, result.exception.code

    def test_direct_download_removes_proxy_only_from_child_environment(self):
        calls, code = self.run_installer([0])
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)
        command = calls[0].args[0]
        self.assertEqual(command[-2:], ['--proxy', ''])
        environment = calls[0].kwargs['env']
        for key in ('HTTP_PROXY', 'https_proxy', 'ALL_PROXY'):
            self.assertNotIn(key, environment)
        self.assertEqual(environment['NO_PROXY'], '*')
        self.assertEqual(environment['KEEP'], 'original')

    def test_proxy_fallback_preserves_original_environment_and_failure_code(self):
        calls, code = self.run_installer([1, 7])
        self.assertEqual(code, 7)
        self.assertEqual(len(calls), 2)
        self.assertNotIn('--proxy', calls[1].args[0])
        self.assertEqual(calls[1].kwargs['env']['HTTP_PROXY'], 'http://example.invalid:8080')
        self.assertNotIn('NO_PROXY', calls[1].kwargs['env'])

    def test_chinese_output_survives_windows_cp1252_redirection(self):
        # 子进程先强制使用会拒绝中文的输出编码；下载命令始终模拟成功。
        code = """import runpy,sys
from unittest.mock import Mock,patch
sys.stdout.reconfigure(encoding='cp1252',errors='strict')
sys.stderr.reconfigure(encoding='cp1252',errors='strict')
with patch.object(sys,'version_info',(3,12)), patch('subprocess.run',return_value=Mock(returncode=0)):
    runpy.run_path(sys.argv[1],run_name='__main__')
"""
        result = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT / 'install_dependencies.py')],
                                capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('正在绕开代理直接下载', result.stdout)
        self.assertNotIn('UnicodeEncodeError', result.stderr)
