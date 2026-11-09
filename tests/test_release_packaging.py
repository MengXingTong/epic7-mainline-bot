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

    def test_all_packaged_local_imports_are_allowlisted_once(self):
        import ast
        root=Path(build.__file__).resolve().parent
        self.assertEqual(len(build.SOURCES),len(set(build.SOURCES)))
        local={p.stem for p in root.glob('*.py')}
        included={Path(name).stem for name in build.SOURCES if name.endswith('.py')}
        for name in build.SOURCES:
            self.assertEqual(Path(name).name,name)
            self.assertTrue((root/name).is_file(),name)
            if not name.endswith('.py'):continue
            for node in ast.walk(ast.parse((root/name).read_text(encoding='utf-8-sig'))):
                modules=([a.name.split('.')[0] for a in node.names] if isinstance(node,ast.Import)
                         else [node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else [])
                for module in modules:
                    if module in local:self.assertIn(module,included,(name,node.lineno,module))
        for name in ('free_notices','story_open_ack','mainline_maintenance','tutorial_core','penguin_worker'):
            self.assertIn(name,included)

    def test_selfcheck_task_contract_matches_the_packaged_gui_declarations(self):
        import ast
        root=Path(build.__file__).resolve().parent
        gui=ast.parse((root/'assistant_app.py').read_text(encoding='utf-8'))
        tasks=next(ast.literal_eval(n.value) for n in gui.body if isinstance(n,ast.Assign)
                   and any(isinstance(t,ast.Name) and t.id=='TASKS' for t in n.targets))
        check=ast.parse((root/'portable_selfcheck.py').read_text(encoding='utf-8'))
        declared=[ast.literal_eval(n.test.comparators[0]) for n in ast.walk(check) if isinstance(n,ast.Assert)
                  and isinstance(n.test,ast.Compare) and ast.unparse(n.test.left)=="ui['tasks']"]
        self.assertEqual(declared,[list(tasks.values())])
        self.assertIn('arena',declared[0])

    def test_update_contains_current_validation_and_no_runtime_or_private_state(self):
        import json,zipfile
        with tempfile.TemporaryDirectory(prefix='epic7-clean-update-') as folder:
            root=Path(folder)/'package';root.mkdir()
            names=set(build.SOURCES)|{'portable.json','BUILD_INFO.json','README_zh-CN.md','VALIDATION.md',
                'STALL_VALIDATION.md','DIMENSION_VALIDATION.md','THEATER_VALIDATION.md','MAINLINE_VALIDATION.md','STEAM_VALIDATION.md',
                'THIRD_PARTY_NOTICES.txt','SHA256SUMS.json','SelfCheck.cmd','启动助手.cmd'}
            for name in names:(root/name).write_text('synthetic package source',encoding='utf-8')
            (root/'portable.json').write_text(json.dumps({'version':build.VERSION}),encoding='utf-8')
            private={'.local/settings.json':b'preserve settings','history/state.json':b'preserve history',
                     'history/evidence/old.png':b'preserve evidence','history/STOP':b'preserve stop'}
            for name,data in private.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
            with zipfile.ZipFile(build.build_update(root)) as archive:
                self.assertIn('MAINLINE_VALIDATION.md',archive.namelist())
                self.assertIn('STEAM_VALIDATION.md',archive.namelist())
                self.assertIn('pc_clients.py',archive.namelist())
                self.assertIsNone(archive.testzip())
                self.assertEqual(set(archive.namelist()),names|{'UPDATE_README.txt'})
                self.assertFalse(any(name.startswith(('gui/','runtime/','vendor/','.local/','history/')) for name in archive.namelist()))
                instructions=archive.read('UPDATE_README.txt').decode('utf-8')
                self.assertIn('v'+build.VERSION.removesuffix('-preview'),instructions);self.assertIn('不删除 .local、state.json、evidence',instructions)
            for name,data in private.items():self.assertEqual((root/name).read_bytes(),data)

    def test_readonly_validation_preset_does_not_use_old_display_label(self):
        root=Path(build.__file__).resolve().parent
        source=(root/'assistant_app.py').read_text(encoding='utf-8')
        self.assertNotIn("app.client.set('PC 桌面端')",source)
        self.assertIn("app.client.set(next(k for k,v in CLIENTS.items() if v=='pc'))",source)
