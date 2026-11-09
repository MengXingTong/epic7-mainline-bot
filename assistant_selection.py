"""Read-only discovery/selection state. No history writes or game input."""
from __future__ import annotations

from collections import Counter
import math
import os


def target_identity(target):
    """Display names/geometry are not identities; recycled PC windows differ."""
    if not isinstance(target, dict):
        raise ValueError('客户端检测结果包含无效实例；请刷新重新核实。')
    client = target.get('client')
    if client == 'pc':
        hwnd, pid, created = (target.get(k) for k in ('hwnd', 'pid', 'created'))
        exe = target.get('exe')
        if (type(hwnd) is not int or hwnd <= 0 or type(pid) is not int or pid <= 0
                or type(created) not in (int, float) or created <= 0
                or isinstance(created, float) and not math.isfinite(created)
                or not isinstance(exe, str) or not exe.strip()):
            raise ValueError('桌面端实例缺少窗口、进程寿命或路径信息；请刷新重新检测。')
        return client, hwnd, pid, created, os.path.normcase(os.path.abspath(exe))
    if client == 'mumu':
        serial, package = target.get('serial'), target.get('package')
        if not isinstance(serial, str) or not serial.strip() or not isinstance(package, str) or not package.strip():
            raise ValueError('MuMu实例缺少设备地址或游戏包信息；请刷新重新检测。')
        serial = serial.strip().lower()
        host, sep, port = serial.rpartition(':')
        if sep and host in ('localhost', '127.0.0.1', '[::1]') and port.isdecimal():
            serial = '127.0.0.1:' + str(int(port))
        index = target.get('mumu_index')
        if index is not None and (type(index) is not int or index < 0):
            raise ValueError('MuMu实例编号无效；请刷新重新检测。')
        return client, serial, package, index
    raise ValueError('检测到未知客户端类型；请刷新重新检测。')


class TargetSelection:
    """Keep an explicit binding across refresh, never fall over to another target.

    A deliberate client-filter change may select its sole candidate. A refresh,
    failed discovery, label change, or missing bound target cannot do that.
    This is a UI cache only, never a progress/profile association.
    """
    def __init__(self):
        self.client = 'auto'
        self.rows = []
        self.labels = []
        self._keys = []
        self._binding = None
        self.phase = 'unscanned'
        self.detail = ''

    def refresh(self, targets, client):
        if client not in ('auto', 'pc', 'mumu'):
            raise ValueError('未知的客户端选项。')
        client_changed = client != self.client
        self.client = client
        self.rows = []
        self._keys = []
        self.labels = []
        self.detail = ''
        try:
            if not isinstance(targets, (list, tuple)) or any(not isinstance(t, dict) for t in targets):
                raise ValueError('客户端检测结果无效；请刷新重新核实。')
            self.rows = [t for t in targets if client == 'auto' or t.get('client') == client]
            self._keys = [target_identity(t) for t in self.rows]
            if len(set(self._keys)) != len(self._keys):
                raise ValueError('检测结果包含重复的实例身份；请刷新重新核实，不自动选择。')
            raw = [t['label'] for t in self.rows]
            if any(not isinstance(label, str) or not label.strip() for label in raw):
                raise ValueError('检测结果缺少实例名称；请刷新重新核实。')
            counts = Counter(raw)
            reserved = set(raw)
            for i, label in enumerate(raw):
                if counts[label] > 1:
                    label = f'{label} · 候选 #{i + 1}'
                    while label in reserved:
                        label += ' ·'
                self.labels.append(label)
                reserved.add(label)
        except (ValueError, KeyError, TypeError) as exc:
            self.phase = 'invalid'
            self.detail = str(exc)
            self.labels = []
            return
        if client_changed and self._binding not in self._keys:
            self._binding = None  # An explicit filter change, not a discovery fallback.
        if not self.rows:
            self.phase = 'empty'
        elif self._binding in self._keys:
            self.phase = 'ready'
        elif self._binding is not None:
            self.phase = 'lost'
        elif len(self.rows) == 1:
            self._binding = self._keys[0]
            self.phase = 'ready'
        else:
            self.phase = 'multiple'

    def fail(self, detail):
        # Keep only the old identity for a later successful discovery, not usable rows.
        self.rows = []
        self.labels = []
        self._keys = []
        self.phase = 'failed'
        self.detail = str(detail)

    def choose(self, label):
        if self.phase in ('unscanned', 'failed', 'invalid') or label not in self.labels:
            raise ValueError(self.message)
        index = self.labels.index(label)
        if target_identity(self.rows[index]) != self._keys[index]:
            raise ValueError('实例身份已变化；请刷新重新检测，不使用旧列表。')
        self._binding = self._keys[index]
        self.phase = 'ready'

    def target(self):
        if self.phase != 'ready':
            raise ValueError(self.message)
        rows = [t for t in self.rows if target_identity(t) == self._binding]
        if len(rows) != 1:
            raise ValueError('原绑定实例已失效或身份发生变化；请刷新后重新选择。')
        return rows[0]

    @property
    def ready(self):
        try:
            self.target()
        except ValueError:
            return False
        return True

    @property
    def display(self):
        if self.ready:
            return self.labels[self._keys.index(self._binding)]
        return {'unscanned': '尚未检测客户端', 'empty': '未检测到所选客户端',
                'multiple': '检测到多个目标，请手动选择', 'lost': '原绑定实例已失效，请重新选择',
                'failed': '检测失败，请刷新', 'invalid': '实例信息异常，请刷新'}.get(self.phase, '请重新选择实例')

    @property
    def message(self):
        if self.phase == 'ready':
            return '已选择 ' + self.labels[self._keys.index(self._binding)] + '；任务尚未启动，点击开始才会运行。'
        if self.phase == 'empty':
            client = {'auto': '可用客户端', 'pc': '电脑客户端', 'mumu': 'MuMu实例'}[self.client]
            return '未检测到' + client + '；请确认客户端/实例已启动、PC窗口未最小化，再点击“刷新”。'
        if self.phase == 'multiple':
            return f'检测到{len(self.rows)}个目标；请在“绑定实例”下拉框中选择一个，再点开始。多个目标不会自动切换。'
        if self.phase == 'lost':
            return '原绑定实例已消失或进程身份发生变化；请在“绑定实例”中重新选择，不会自动切换到其他目标。'
        if self.phase == 'failed':
            return '客户端检测失败，原候选列表已作废；请点击“刷新”重新检测。' + self.detail
        if self.phase == 'invalid':
            return self.detail
        return '尚未检测客户端；请点击“刷新”，再选择具体实例。'
