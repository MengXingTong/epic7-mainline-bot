"""中文展示回归：只使用合成输入、参数解析和源码，不操作游戏。"""
import ast
import contextlib
import io
import json
import sys
import subprocess
import unittest
from pathlib import Path

from assistant_status import scene_caption
from ui_text import ChineseArgumentParser, SCENE_NAMES, error_text, scene_name

ROOT = Path(__file__).resolve().parents[1]


class ChinesePresentationTests(unittest.TestCase):
    def test_every_mainline_scene_has_a_chinese_caption(self):
        tree = ast.parse((ROOT / 'runner.py').read_text(encoding='utf-8'))
        classifier = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'classify')
        scenes = {n.value.value for n in ast.walk(classifier)
                  if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)}
        self.assertTrue(scenes)
        self.assertLessEqual(scenes, SCENE_NAMES.keys())
        for scene in scenes:
            with self.subTest(scene=scene):
                self.assertRegex(scene_caption({'scene': scene}), r'[\u4e00-\u9fff]')
                self.assertNotEqual(scene_caption({'scene': scene}), scene)

    def test_scene_display_does_not_mutate_protocol_or_farming_count(self):
        values = {'scene': 'battle', 'story_mode': 'farm', 'stage': '3-7', 'farm_runs': 4}
        original = dict(values)
        self.assertEqual(scene_caption(values), '3-7 · 已成功 4 次')
        self.assertEqual(values, original)
        self.assertEqual(scene_name('Rank升级提示'), '等级提升提示')
        self.assertEqual(scene_name('普通深渊选层 · 第52层'), '普通深渊选层 · 第52层')
        self.assertEqual(scene_name('future_scene'), '尚未确认的画面')
        self.assertEqual(scene_caption({}), '—')

    def test_help_headings_and_builtin_help_are_chinese(self):
        parser = ChineseArgumentParser(prog='assistant')
        parser.add_argument('command', choices=['check', 'start'])
        parser.add_argument('--task', choices=['mainline', 'abyss'])
        text = parser.format_help()
        for phrase in ('用法：', '位置参数', '可选参数', '显示此帮助信息后退出', '任务：'):
            self.assertIn(phrase, text)
        for phrase in ('usage:', 'positional arguments:', 'options:', 'show this help message'):
            self.assertNotIn(phrase, text)
        self.assertIn('--task', text)
        self.assertEqual(parser.parse_args(['start', '--task', 'abyss']).task, 'abyss')

    def test_parser_error_paths_remain_fail_closed_in_chinese(self):
        parser = ChineseArgumentParser(prog='assistant')
        parser.add_argument('command', choices=['check', 'start'])
        parser.add_argument('--delay', type=int)
        parser.add_argument('--ui-check', action='store_true')
        parser.add_argument('--ui-exercise', action='store_true')
        cases = [([], '缺少以下必需参数'), (['other'], '无效选项'),
                 (['start', '--unknown'], '无法识别的参数'),
                 (['start', '--delay'], '需要提供一个参数值'),
                 (['start', '--delay', 'abc'], '无效整数'),
                 (['start', '--ui'], '选项有歧义'),
                 (['start', '--ui-check=yes'], '不接受附加值')]
        for args, expected in cases:
            with self.subTest(args=args), contextlib.redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as result:
                    parser.parse_args(args)
                self.assertEqual(result.exception.code, 2)
                self.assertIn(expected, output.getvalue())
                self.assertNotIn('error:', output.getvalue())

    def test_system_errors_show_chinese_and_preserve_original_exception(self):
        exc = PermissionError(13, 'Permission denied', 'state.json')
        self.assertIn('访问被拒绝', error_text(exc))
        self.assertIn('13', error_text(exc))
        self.assertIn('state.json', error_text(exc))
        self.assertEqual(exc.strerror, 'Permission denied')
        self.assertIn('文件或路径不存在', error_text(FileNotFoundError(2, 'missing', 'game.exe')))
        self.assertIn('超时', error_text(subprocess.TimeoutExpired('worker', 25)))
        self.assertIn('退出码 3', error_text(subprocess.CalledProcessError(3, 'worker')))
        self.assertEqual(error_text(ValueError('目标已变化')), '目标已变化')
        self.assertIn('第 1 行', error_text(json.JSONDecodeError('Invalid JSON', '{', 1)))
        self.assertIn('文本编码无效', error_text(UnicodeError('invalid text')))
        self.assertIn('运行依赖无法加载（PIL）', error_text(ModuleNotFoundError('missing', name='PIL')))

    def test_all_project_owned_exception_messages_are_chinese(self):
        for path in ROOT.glob('*.py'):
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
                    continue
                if not node.exc.args:
                    continue
                first = node.exc.args[1] if isinstance(node.exc.func, ast.Name) and node.exc.func.id == 'TaskAttention' else node.exc.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    with self.subTest(file=path.name, line=node.lineno):
                        self.assertRegex(first.value, r'[\u4e00-\u9fff]')

    def test_launch_script_uses_utf8_and_chinese_failure_text(self):
        text = (ROOT / 'Assistant.cmd').read_text(encoding='utf-8')
        self.assertIn('chcp 65001', text)
        self.assertIn('缺少界面运行库', text)
        self.assertNotIn('GUI runtime missing', text)

    def test_shared_text_module_is_packaged(self):
        import build_portable
        self.assertIn('ui_text.py', build_portable.SOURCES)

    def test_rank_recognition_keeps_original_game_text(self):
        from task_overlays import rankup_splash
        words = [dict(text=t, x=x, y=y) for t, x, y in [
            ('RANKUP', 800, 270), ('23', 800, 337),
            ('账号Rank提升，已恢复97点行动力。', 800, 776), ('请继续您的旅程吧！', 800, 810)]]
        self.assertTrue(rankup_splash(words))
        words.append(dict(text='购买', x=800, y=400))
        self.assertFalse(rankup_splash(words))

    def test_script_help_loads_local_text_module_without_starting_tasks(self):
        for script in ('launcher.py', 'assistant_worker.py', 'assistant_control.py',
                       'pc_launcher.py', 'pc_quickstart.py', 'build_portable.py',
                       'portable_selfcheck.py', 'runner.py'):
            with self.subTest(script=script):
                result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT / script), '--help'],
                                        cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('用法：', result.stdout)
                self.assertNotIn('usage:', result.stdout)
                self.assertIn('显示此帮助信息后退出', result.stdout)
