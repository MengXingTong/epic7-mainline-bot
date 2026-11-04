"""中文展示层；不改写识别标签、配置键、命令或持久化协议。"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys


SCENE_NAMES = {
    'attention': '等待处理',
    'capacity_stop': '容量不足（等待处理）',
    'resource_stop': '资源提示（等待处理）',
    'network_error': '网络连接异常',
    'defeat': '战斗失败',
    'account_upgrade_notice': '账号升级提示',
    'friendship_upgrade_notice': '英雄亲密度提升提示',
    'rankup_splash': '等级提升全屏提示',
    'rankup': '等级提升提示',
    'friend_decline': '好友申请提示',
    'tutorial_skip_confirm': '跳过教学确认',
    'tutorial_skip': '教学画面',
    'skip_confirm': '跳过剧情确认',
    'unknown_dialog': '尚未确认的弹窗',
    'story_reward': '剧情奖励',
    'unlock_notice': '支线解锁提示',
    'settlement': '通关结算',
    'bond_notice': '缘分解锁提示',
    'legacy_story_regions': '旧版剧情地区总览',
    'legacy_story_map': '旧版剧情地图',
    'legacy_story_clear': '旧版剧情胜利过场',
    'legacy_story_exit': '旧版剧情出口',
    'post_clear_exit': '通关后离开页面',
    'story': '剧情播放',
    'victory': '战斗胜利过场',
    'map': '主线地图',
    'support': '辅助英雄选择',
    'team': '队伍准备',
    'lobby': '游戏大厅',
    'battle': '自动战斗中',
    'result_transition': '结算过场',
    'loading': '加载中',
    'unknown': '尚未确认的画面',
    'Rank升级提示': '等级提升提示',
}


def scene_name(scene):
    """只转换展示文案；未知代码不显示成已确认的游戏状态。"""
    scene = str(getattr(scene, 'value', scene) or '—')
    name, separator, suffix = scene.partition(' · ')
    label = SCENE_NAMES.get(name)
    if label is None:
        label = name if not re.search(r'[A-Za-z]', name) else '尚未确认的画面'
    return label + separator + suffix


ACTION_NAMES = {'stop': '停止', 'pause': '暂停', 'resume': '继续',
                'restart': '重启工作进程', 'status': '查看状态'}

ARGUMENT_HELP = {
    'command': '执行命令（保留原有命令名称）',
    'action': '操作：stop 停止、pause 暂停、resume 继续、restart 重启工作进程、status 查看状态',
    '--task': '任务：mainline 剧情关卡、abyss 普通深渊、saint_3_7 圣女3-7',
    '--client': '客户端：auto 自动识别、mumu 模拟器、pc 实验性桌面端',
    '--autostart': '检测到唯一客户端后开始任务',
    '--ui-check': '仅检查界面，不启动游戏任务',
    '--ui-exercise': '以只读方式验证界面，不发送游戏输入',
    '--request': '本机私有任务请求文件路径',
    '--discover': '仅检测客户端，读取指定的本机设置文件',
    '--config': '本机配置文件路径',
    '--delay': '旧版前台工具的等待秒数（不适用于统一界面）',
    '--observe': '旧版工具的只读观察模式，不发送游戏输入',
    '--step': '旧版工具仅检查一次当前画面',
    '--worker': '仅执行离线工作运行库检查',
    '--output': '新发布包输出目录（禁止覆盖已有目录）',
    '--gui-runtime': '界面运行库目录',
    '--worker-runtime': '工作运行库目录',
    '--vendor': '第三方依赖目录',
    '--glyphs': '已验证的二值字形资源目录',
    '--zip': '同时生成离线压缩包',
}


def argument_error(message):
    """转换标准参数解析器的错误，不翻译参数名和用户输入值。"""
    replacements = (
        ('ambiguous option:', '选项有歧义：'),
        ('could match', '可能对应'),
        ('ignored explicit argument', '不接受附加值'),
        ('one of the arguments', '以下参数中至少一个'),
        ('is required', '为必需参数'),
        ('the following arguments are required:', '缺少以下必需参数：'),
        ('unrecognized arguments:', '无法识别的参数：'),
        ('invalid choice:', '无效选项：'),
        ('choose from', '可选值为'),
        ('expected one argument', '需要提供一个参数值'),
        ('expected at least one argument', '至少需要提供一个参数值'),
        ('expected at most one argument', '最多只能提供一个参数值'),
        ('not allowed with argument', '不能与此参数同时使用：'),
        ('expected ', '需要提供 '),
        (' arguments', ' 个参数值'),
    )
    for source, target in replacements:
        message = message.replace(source, target)
    message = re.sub(r'invalid (int|float|Path) value:',
                     lambda m: {'int': '无效整数：', 'float': '无效数字：', 'Path': '无效路径：'}[m[1]], message)
    return re.sub(r'\bargument ', '参数 ', message)


class ChineseHelpFormatter(argparse.HelpFormatter):
    def _format_usage(self, usage, actions, groups, prefix):
        return super()._format_usage(usage, actions, groups, prefix or '用法：')


class ChineseArgumentParser(argparse.ArgumentParser):
    """原命令接口保持不变，只将帮助和参数校验提示改为中文。"""
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('formatter_class', ChineseHelpFormatter)
        kwargs.setdefault('description', '第七史诗助手命令行工具。统一界面仍为推荐入口；桌面端适配为实验性。')
        add_help = kwargs.pop('add_help', True)
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = '位置参数'
        self._optionals.title = '可选参数'
        if add_help:
            self.add_argument('-h', '--help', action='help', help='显示此帮助信息后退出')

    def add_argument(self, *args, **kwargs):
        if args and 'help' not in kwargs:
            kwargs['help'] = ARGUMENT_HELP.get(args[0], '命令参数')
            if args[0] == 'command' and kwargs.get('choices'):
                names = {'check': '检查', 'start': '开始', 'stop': '停止', 'resume': '继续',
                         'selftest': '离线自检', 'reconcile': '补记人工通关'}
                kwargs['help'] = '命令：' + '、'.join(f'{key} {names.get(key, key)}' for key in kwargs['choices'])
        if args and 'metavar' not in kwargs:
            metavar = {'--request': '请求文件', '--discover': '设置文件', '--config': '配置文件',
                       '--delay': '秒数', '--output': '输出目录', '--gui-runtime': '界面运行库',
                       '--worker-runtime': '工作运行库', '--vendor': '依赖目录', '--glyphs': '字形目录'}
            if args[0] in metavar:
                kwargs['metavar'] = metavar[args[0]]
        return super().add_argument(*args, **kwargs)

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(2, f'{self.prog}：参数错误：{argument_error(message)}\n')


def error_text(exc):
    """为系统异常提供中文原因；原异常仍由调用方保留在诊断日志中。"""
    if isinstance(exc, ImportError):
        name = getattr(exc, 'name', None)
        detail = f'（{name}）' if name else ''
        return '运行依赖无法加载' + detail + '；请完整解压离线包，源码环境请先运行 install_dependencies.py。'
    if isinstance(exc, json.JSONDecodeError):
        return f'JSON 文件格式错误（第 {exc.lineno} 行，第 {exc.colno} 列）；请检查原文件，不要删除进度记录。'
    if isinstance(exc, UnicodeError):
        return '文本编码无效；请检查文件编码，不要删除原始记录。'
    if isinstance(exc, subprocess.TimeoutExpired):
        return f'等待子进程响应超时（{exc.timeout} 秒），已停止当前操作。'
    if isinstance(exc, subprocess.CalledProcessError):
        return f'子进程执行失败（退出码 {exc.returncode}），请检查本机日志。'
    if isinstance(exc, OSError):
        reason = ('访问被拒绝' if isinstance(exc, PermissionError) else
                  '文件或路径不存在' if isinstance(exc, FileNotFoundError) else '系统操作失败')
        code = getattr(exc, 'winerror', None) or exc.errno
        detail = f'（系统错误 {code}）' if code is not None else ''
        path = f'：{exc.filename}' if exc.filename else ''
        return reason + detail + path + '；已停止当前操作。'
    return str(exc)
