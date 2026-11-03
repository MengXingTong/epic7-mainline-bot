"""发布源码复制回归；仅操作临时文本，不复制运行库或产生游戏输入。"""
import tempfile
from pathlib import Path
import unittest

import build_portable as build


class ReleasePackagingTests(unittest.TestCase):
    def test_chinese_cmd_is_utf8_with_exactly_crlf_line_endings(self):
        with tempfile.TemporaryDirectory(prefix='epic7-发布编码-') as folder:
            root=Path(folder);source=root/'中文 启动.cmd';target=root/'输出.cmd'
            original='@echo off\nchcp 65001 >nul\necho 缺少界面运行库，请完整解压。\n'
            source.write_bytes(original.encode('utf-8'))
            build.copy_source_file(source,target)
            self.assertEqual(target.read_bytes(),original.replace('\n','\r\n').encode('utf-8'))
            self.assertNotIn(b'\r\r\n',target.read_bytes())

    def test_existing_crlf_cmd_and_bom_are_normalized_without_corruption(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'start.CMD';target=root/'output.CMD'
            source.write_bytes(b'\xef\xbb\xbf'+'@echo off\r\necho 中文\r\n'.encode('utf-8'))
            build.copy_source_file(source,target)
            self.assertEqual(target.read_bytes(),'@echo off\r\necho 中文\r\n'.encode('utf-8'))

    def test_non_cmd_source_is_copied_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.py';target=root/'target.py'
            content='# 中文源码\r\nVALUE = "保留"\n'.encode('utf-8')
            source.write_bytes(content);build.copy_source_file(source,target)
            self.assertEqual(target.read_bytes(),content)

    def test_share_instructions_match_preview_version(self):
        root=Path(build.__file__).resolve().parent
        readme=(root/'docs'/'SHARE_README.md').read_text(encoding='utf-8')
        self.assertIn('v'+build.VERSION.removesuffix('-preview'),readme.splitlines()[0])
        self.assertIn('实验性',readme)
        self.assertIn('不要删除.local、state.json、evidence或原进度',readme)

    def test_readonly_validation_preset_does_not_use_old_display_label(self):
        root=Path(build.__file__).resolve().parent
        source=(root/'assistant_app.py').read_text(encoding='utf-8')
        self.assertNotIn("app.client.set('PC 桌面端')",source)
        self.assertIn("app.client.set(next(k for k,v in CLIENTS.items() if v=='pc'))",source)
