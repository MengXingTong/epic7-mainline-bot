"""Presentation-only activity states. Never infer gameplay from process existence."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Activity:
    title: str
    color: str
    moving: bool = False


def activity(mode, task="mainline", observe=True, alive=False):
    task_name = {'mainline':'剧情关卡','saint_3_7':'圣女3-7'}.get(task,'普通深渊')
    if mode in ("starting", "checking") and alive:
        return Activity("检查中 · 尚未进入关卡", "#2465a4", True)
    if mode in ("run", "observe") and not alive:
        return Activity("已停止 · 工作进程不在运行", "#a63d34")
    states = {
        "idle": Activity("未启动 · 当前没有任务在运行", "#65776f"),
        "recovering": Activity("正在恢复画面 · 暂停输入", "#956116", True),
        "attention": Activity("等待处理 · 已暂停操作", "#956116"),
        "scanning": Activity("检测客户端中 · 尚未启动任务", "#2465a4", True),
        "starting": Activity("未启动 · 正在准备", "#2465a4"),
        "checking": Activity("未启动 · 正在检查配置", "#2465a4"),
        "observe": Activity("正在观察 · 不会点击游戏", "#2465a4", True),
        "run": Activity(("正在观察 · 不会点击游戏" if observe else "正在推进 · " + task_name), "#2465a4" if observe else "#087b65", True),
        "pausing": Activity("正在暂停 · 等待工作进程确认", "#956116", True),
        "paused": Activity("已暂停 · 不发送操作", "#956116"),
        "stopping": Activity("正在停止 · 等待工作进程退出", "#956116", True),
        "stopped": Activity("已停止 · 不发送操作", "#65776f"),
        "done": Activity("已完成 · 本次任务结束", "#087b65"),
        "blocked": Activity("未运行 · 需要处理下方原因", "#a63d34"),
    }
    return states.get(mode, Activity("状态未知 · 不代表正在推进", "#a63d34"))


def scene_caption(values):
    """Compact progress text; successful farming count never means active entry won."""
    stage=values.get('stage','')
    if values.get('story_mode')=='farm' and stage:
        return f"{stage} · 已成功 {values.get('farm_runs',0)} 次"
    return values.get('scene','—')
