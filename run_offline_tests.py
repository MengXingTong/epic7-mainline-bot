"""统一离线测试入口；仅加载依赖和运行测试，不发现客户端或发送游戏输入。"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent


def configure_paths():
    """在测试发现之前加载本仓库和 --target vendor 安装的依赖。"""
    required = [str(ROOT), str(ROOT / 'vendor')]
    sys.path[:] = required + [path for path in sys.path if path not in required]


def check_dependencies(require_gui=False):
    """缺少依赖必须失败，不能被界面测试误当成缺少 Tk 而跳过。"""
    names = ['PIL.Image', 'cv2', 'numpy', 'rapidocr_onnxruntime']
    if require_gui:
        names += ['tkinter', 'PIL.ImageTk', 'assistant_app']
    for name in names:
        importlib.import_module(name)


def main(argv=None):
    configure_paths()
    from ui_text import error_text
    try:
        check_dependencies(require_gui=os.environ.get('EPIC7_REQUIRE_GUI_TESTS') == '1')
    except (ImportError, OSError) as exc:
        print('离线测试依赖检查失败：' + error_text(exc), file=sys.stderr)
        return 1
    args = list(sys.argv[1:] if argv is None else argv)
    result = unittest.main(module=None,
                           argv=[str(ROOT / 'run_offline_tests.py'), 'discover', '-s', str(ROOT / 'tests'), *args],
                           exit=False).result
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
