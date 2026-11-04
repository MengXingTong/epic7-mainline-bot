# Offline test suites

- `test_safety.py`: resource veto, paid revival, no-repeat entry, verification chain and recognized UI regressions.
- `test_launcher.py`: environment selection, foreground package check, safe manual resume, Unicode paths and aspect-ratio validation.

No test sends game input. Launcher tests use temporary directories and mocks; safety tests replace logging/input/persistence with in-memory fakes.

Real game screenshots and OCR fixtures are deliberately excluded. Set `EPIC7_PRIVATE_FIXTURES` to a local directory to run those additional cases. Without it the fixture-dependent cases are explicitly skipped, not reported as passed.

## Experimental PC tests

- `test_pc_backend.py`: mock transport guards, window/DPI/multi-monitor geometry matrix, profile/account checks, initialization failures and non-destructive manual reconciliation. Native Windows API declarations are inspected using mocked DLLs; no native capture or input is executed.
- `test_pc_fixtures.py`: optional saved PC map images, enabled only with `EPIC7_PC_FIXTURES` pointing at a private local directory. These are classifier regressions, not native input acceptance.

A passed geometry matrix does not mean every monitor, GPU, DPI mode or game UI has been tested live. PC input remains opt-in and experimental.

- `test_pc_quickstart.py`: automatic account field discovery, bounded startup navigation, no daily configuration prompts, legacy history reuse, safe first-use initialization, account mismatch/active guards, read-only behavior and STOP restoration; all native APIs are faked.

## Legacy story and Saint 3-7

`test_story.py` covers exact preparation-stage reads, three/five-wave CLEAR, blue exits before/after settlement, native region routes, map panning, task switching and success-only repetition. Its synthetic policy cases run without private screenshots and never call native input. Saved-image regressions use `EPIC7_STORY_FIXTURES` (local `.local/story-validation` by default); absent private fixtures are explicitly skipped. `test_pc_backend.py` also checks drag cancellation, geometry changes, frame consumption and paired release using fakes.

## 中文展示回归

`test_localization.py` 检查全部主线场景的中文显示名称、命令行帮助和参数错误、项目自定义异常提示、系统错误格式、启动脚本编码，以及新文案模块是否进入打包白名单。保留命令与配置协议，等级提示识别仍使用原游戏文字。`test_activity_gui.py` 补充界面标题和原始场景代码的中文展示；`test_launcher.py` 同时验证中文与旧英文确认词均保留原进度保护。全部使用隔离数据或模拟后端，不产生游戏输入。

## 统一测试入口与 CI 依赖

源码依赖由 `install_dependencies.py` 安装到 `vendor`，请使用 `python -B -X utf8 run_offline_tests.py -v` 运行全套测试，保证在导入首个测试前加载依赖目录。GitHub Actions 额外设置 `EPIC7_REQUIRE_GUI_TESTS=1`；Pillow、Tk 或界面导入失败均报错，不再被误判为可跳过的“没有界面运行库”。`test_test_entrypoint.py` 覆盖路径顺序、依赖预检、严格界面模式和失败退出码，使用模拟依赖，不进行游戏下载、打包或游戏输入。

`test_install_dependencies.py` 通过模拟全部下载调用验证直连优先、原代理回退、不修改全局环境和非零退出码，并在隔离子进程中强制 cp1252 重定向输出，确认中文安装提示不会崩溃；不会真正下载或安装依赖。

## 队伍准备页

`test_team_preparation.py` 验证带AUTO与辅助英雄空位两类布局、仅普通单次入场、地图链/体力/历史/弹窗优先、关键落盘和发送不明防重；输入及状态保存均使用模拟对象。可通过 `EPIC7_TEAM_FIXTURES` 指向含 `team.png`、`team-ocr.json` 的本机目录回放报告画面，默认使用本机私有回放目录；缺少文件明确跳过，素材不随源码分发，不操作游戏。

`test_friendship_notice.py` 验证好感度提示只操作本帧关闭控件，包括其覆盖在带右下角“确认”的战斗结算页时；只有“获得的道具”“战斗结果”和唯一结算确认同时成立才忽略底层按钮，其他确认、资源、复活、容量与战败覆盖层继续拦截。私有保存画面仅做离线OCR回放，不随源码分发。
