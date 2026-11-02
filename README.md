# Epic Seven Mainline Bot / 第七史诗主线助手

本地 Windows Python 脚本，基于截图 + OCR 和保守状态机推进《第七史诗》主线。

## 支持状态

| 目标 | 状态 |
|---|---|
| MuMu Android 国际服、简体中文 UI、16:9 | 已实机运行；使用本地 ADB |
| STOVE 官方 PC 客户端 | **实验性原生后端已加入，默认只读；完整实机验收未完成** |

原 MuMu 离线分享包仍可使用。仓库仅保存可维护源码，不含 Python/OCR 运行库、游戏/ADB 二进制或账号数据。

## 更新与维护

变更记录见 [CHANGELOG](CHANGELOG.md)，维护与发布检查见 [开发说明](docs/DEVELOPMENT.md)。

## STOVE PC（实验性）

不要求全屏。按实际游戏客户区和 DPI 映射坐标，不依赖显示器的固定分辨率。先阅读 [PC 使用说明与边界](docs/PC_GUIDE.md)，用 PCCheck 进行只读账号/服务器核对。默认 `experimental_input_enabled: false`；未经验收不要直接无人值守启动。

## 快速开始（MuMu）

需要 Windows x64、Python 3.12、MuMu 及已登录的游戏。

```powershell
py -3.12 install_dependencies.py
py -3.12 launcher.py selftest
py -3.12 launcher.py check
py -3.12 launcher.py start
```

也可使用 Check.cmd / Start.cmd / Stop.cmd / Resume.cmd。启动需输入 START；安全续跑需输入 RESUME。
详细配置、停止与恢复见 [MuMu 使用说明](docs/MUMU_GUIDE.md)。

**同一账号、同一服务器在 MuMu 与 PC 之间切换时必须复用完整进度记录，不能通过新建空状态重打已尝试关卡。** 不同账号/服务器使用隔离目录；账号不明时不启动、不自动复制或清空记录。

## 安全底线

- 不使用生命之叶、天空石、道具、货币购买或兑换体力；只允许正常关卡入场体力。
- 不付费复活、不自动重试失败关卡，不强化装备或培养角色，不发送好友请求。
- 新关必须完成地图 → 辅助 → 队伍的匹配校验；未通关蓝色节点且无绿色勾/锁才允许入场。
- 先持久化 attempted 再发送一次入场操作；结果不明不再次入场。
- 只对白名单剧情跳过、结算和免费通知执行对应操作；未知界面停止。
- 人工补过后恢复必须核验原关卡绿色通关勾；所有原始记录保留。

界面变化、网络错误和 OCR 误识别无法保证绝无故障；请先现场短时间观察并自行确认游戏使用规则和账号风险。无反检测、安全绕过或内存修改功能。

## 测试

```powershell
py -3.12 -m unittest discover -s tests -v
```

默认离线测试不连接游戏、无点击。涉及真实截图的回归素材不随仓库分发；本机可用 `EPIC7_PRIVATE_FIXTURES` 与 `EPIC7_PC_FIXTURES` 指定自己的私有素材目录，缺少时明确跳过。

## 项目结构

- `runner.py`：识别、校验链、持久化与动作状态机
- `pc_backend.py` / `pc_launcher.py`：实验性 Windows 客户区后端与严格只读预检
- `runtime_paths.py` / `state_tools.py`：共享账号运行目录与保留原尝试的人工补记
- `supervisor.py`：有界重启与进程锁
- `launcher.py`：MuMu 检查、启动、停止和安全续跑
- `tests/`：离线安全与边界回归
- `docs/`：操作、架构和适配记录

本项目不包含 Codex 定时巡检服务；本地守护不会自动修复新 BUG。账号进度、配置、日志和截图全部留在本机，并由 .gitignore 排除。
