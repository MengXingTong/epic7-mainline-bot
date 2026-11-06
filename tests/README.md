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

`test_stall_recovery.py` 覆盖CLEAR过渡帧到完整结算的连续观察、长时间画面/控件运动、缓慢渐变、轻微OCR位置抖动、稳定未知弹窗、停止打断、规划前过期重取与规划后异常保留意图、确认按钮位置/置信度/唯一性及底图弹窗优先。全部输入和历史使用模拟对象；`EPIC7_STALL_FIXTURES` 可指定私有事故回放目录，缺少则明确跳过。`test_abyss_wait.py` 补充深渊变化弹窗零输入与稳定后等待处理；`test_input_ux_gui.py` 检查等待画面时的暂停/停止和主按钮文字颜色。

## 新号教学与当前run维护

`test_tutorial.py`/`test_tutorial_ocr.py` 使用合成帧检查欢迎信、免费星星奖励、固定队伍基础攻击、双技能布局、教学跳过优先、未知引导零输入、双新帧/同页防重、关键写盘及角色姓名当前固定ROI复核。`test_era_map.py` 检查时代标题、缩小的绿色圈/双臂勾、当前纯剧情原入场链的裁切前行，推断行永不可点击、不推断星级。`test_mainline_maintenance.py` 检查原run来源哈希、目标/设置/停止/进程/STOP保护与显式单次免费故事重开消费；模拟失败/not_sent也不重用，保留原attempted及sent记录。所有输入与进程查询均模拟，不执行游戏操作，不携带账号或截图素材。


`test_team_tutorial.py` 覆盖英雄选择面板含底层“进行任务”及部分OCR缺字时的入场否决、独立已配置标识/等级/血条/占位证据、原关卡配置链逐步持久防重、双新帧一次关闭、写盘失败/发送不明/not_sent不重发，以及已有active不归档/不返回。所有输入均模拟；`EPIC7_TUTORIAL_TEAM_FIXTURES` 可指向本机事故截图目录供生产OCR离线回放，缺失明确跳过，不随源码分发，不控制游戏。普通教学页面识别仍不等于实际开战授权。

## Penguin Nest purchase mode (experimental PC)

- `test_penguin.py`: exact item/modal/quantity/price/currency fields, missing/low-confidence/duplicate/wrong-product vetoes, current maximum rather than hard-coded batch sizes, precise tail adjustment, full-order budget checks, persisted intent-before-dispatch, same-target independent balance proof, pending/unknown/not-sent protection, unmodified mainline history and retained prior orders.
- `test_penguin_worker.py`: fake-transport full worker orders of 51 (50+1) and 49 (Most then -1), no extra purchase, unexpected slider changes, mouse takeover before final down, persistent same-dialog/no-result dedup, unknown-screen zero input and insufficient full budget. No Windows capture/input APIs execute.
- `test_penguin_gui.py`: required total count, task-specific field visibility, runtime locking, original unlimited battle modes, PC-only/observe rejection. Tk tests require the GUI runtime and are explicitly skipped in the embedded worker Python.

Actual client screenshots/OCR/navigation evidence stay under ignored `.local`, never in fixtures or release sources. Live navigation/quantity acceptance is not proof of final resource deduction or post-purchase/multi-batch acceptance; those await an explicitly specified test quantity.

- `test_tutorial_summon_return.py`：原免费圣约链后的仅返回导航；当前付费按钮零点击、私有返回字形完整性/暗化、双帧与来源链、持久发送防重，不将模拟测试当作抽取成功或主线通关。

- `test_free_team_autoconfig.py` 和 `test_team_preparation.py` 原生Episode队伍专项：完整免费自动配置、已有地图/历史链、双帧与按关防重，以及无可用辅助/AUTO的三队标签单次入口；不扩展付费/强化或入场重试。

- `test_spirit_altar_notice.py`：精灵祭坛与英雄觉醒完整功能说明只关闭；用途字段本帧双读，不覆盖原错误/低置信OCR，不把通知关闭当成觉醒或通关。

- 高亮空位专项另测真实Runner优先配置且不产生入场记录、相邻分离蓝环/蓝色身体区分；卡片等级与星级合并时只加强当前数字字段并保留原OCR。私有现场接续与源哈希只写本地账号记录。

- `test_first_entry_power_warning.py`：仅原唯一sent/完整无其他输入链的首次战力差确认；不点不再显示、不新建入场、不重试；缺损文案/资源/容量/失败/归档/剧情战斗链/发送未知均拒绝。章节阈值紧框和单次任务标签的当前双读专项见 `test_tutorial_ocr.py`。

## 剧情跳过与结算聊天误点保护

`test_story_skip_guard.py` 验证唯一/精确/高置信右上角跳过、残留结果字段否决、完整聊天面板（含连接动画）直接进入等待处理、残缺聊天标题阻断底层控件、发送前完整页面重识别、即时文字框双尺度纯识别均≥0.98且同值、控件局部像素/几何/一秒有效期、窗口/视口/截图尺寸变化、短黑帧零输入重观察、关键保存/证据失败，以及背景动画不等整屏静止。输入、进程和历史均模拟；不修改真实进度，不自动关闭聊天或重入关卡。

可将 `EPIC7_CHAT_GUARD_FIXTURE` 指向本机私有目录，提供 `chat.png`、`chat-ocr.json`（含 `words`）及可选 `story.png`，回放聊天事故并用生产OCR验证正常剧情文字框。缺少素材明确跳过，不将本地账号截图、OCR和证据提交或打包。

## 统一助手预览文件竞争

`test_preview.py` 仅对展示缩略图模拟写入/替换失败，覆盖 Windows 真实无删除共享句柄、唯一临时文件/旧预览保留、后续恢复、警告与业务状态隔离、Stop 仍生效、状态持久化失败继续抛出。测试不启动客户端或发送游戏输入；入场/状态/证据不纳入 best-effort 范围。免费自动配置测试显式区分模拟帧采集时间，不依赖 Windows 墙钟在相邻两次函数调用间必定递增。

## 免费故事入口消息应答

`test_story_open_ack.py` 区分原消息sent、实际游戏接受和独立completed。覆盖原唯一入口保留、同run/窗口/双新帧/未完成节点及后继锁保护、2次额外消息的持久防重、任何实际流程/失败/其他输入否决、保存/证据/发送异常，以及明确维护来源和原run重载。原模拟记录仍为sent，不伪装not_sent，不修改通关表；全部输入模拟。私有现场截图和事件来源留在忽略目录。

`test_tutorial_completed_notice.py` 验证完整未翻译教学通知的高置信/唯一/位置与陌生文案否决、关键持久化失败、原run单次关闭且不记通关。`test_era_map.py` 另测3条高置信编号行缺1条中间OCR时的编号归一化行距，仍需独立绿环/内部勾；不降低0.85行阈值、不生成可点击推测节点或星级。

## 高频免费通知、鼠标悬停及最新展示图文件竞争

`test_tutorial_completed_notice.py` 现测背景“确认自己”不误作按钮、已知免费正文表/未知命名空间拒绝、按次通知双帧关闭/消失后重新待命、未知/OCR缺字/仍有弹窗边框不解锁、旧run/关卡关闭记录保留、同一次有界重发与关键留证失败。`test_input_ux.py` 增加客户区悬停/移动零抢焦点且不中断、实际按住鼠标仍保护。`test_capture_display.py` 覆盖独立截图+OCR留证后才容忍展示替换错误、Win32真实不共享删除句柄与恢复，关键证据/编码/临时写入/事件记录失败仍抛出；不通过旧latest授权输入。

`test_map_number_verification.py` 独立验证本帧地图编号，不提高低置信名称分数：两个≥0.98编号读数必须与当前原前缀一致，唯一蓝色当前行与本帧裁剪哈希/采集时间绑定，画面/数字变化、未知弹窗或读数不一致均拒绝。当前私有实图编号双读>0.999，仍不把罗马数字后缀伪造为高置信名称。

- `test_story_open_ack.py` now also exercises the production notice→dismissal→same-entry response chain, the one-frame disappearance race, legacy receipt/pixel replay, OCR gaps, repeated occurrences, mutated/foreign/incomplete receipts, paid/archived/accepted entries and critical evidence/journal failures. All input remains mocked; a passed chain test is not a live game acceptance.

- `test_navigation_input_defer.py`: no-input-before-down typed recovery for exact ordinary UI scenes, fresh worker recapture, active story/result controls, and exclusions for entry/durable intents/ambiguous sends/window/critical writes. Physical input is mocked. `test_free_story_handoff.py` additionally covers regular Episode and arbitrary current star tiers plus no-input passive observations; archives and extra actions remain vetoes.

## 入场响应等待与瞬时全局按住

`test_entry_response_timing.py` 覆盖原入场15秒零输入观察被全局按住等待打断后的剩余截止时刻、不延时/不补发、普通UI重新规划及业务拦截优先。两项测试运行真实 `mainline_run` 循环并模拟按住/松开/独立截图，核对只发生一次原入场、attempted/sent/active/旧失败保留且不写completed。全部输入、窗口、时钟及状态根使用模拟或临时目录，不操作实际游戏；不能据此声称耗体力战斗补发已获授权或实机验证通过。

## 地图数字前缀与分隔点

`test_map_number_verification.py` 的分隔点补强分支只在原数字一致时使用当前前缀内的数字组件裁剪，覆盖1/2位任意测试数字、四读/双读阈值、不同数字/标点/非数字拒绝、缺失/多余/断裂组件、原名称置信度不变、截图时间/像素/编号绑定和未知弹层优先。可用 `EPIC7_MAP_PREFIX_FIXTURE` 指向含 `source.png` 与 `source-ocr.json` 的私有回放目录；缺失则明确跳过生产OCR回放，私有账号图不随源码提交。所有测试均离线，不发送游戏输入或改写入场记录。

## 章末裁切故事结果的严格两行分支

`test_recorded_clipped_story_results.py` 覆盖当前原故事的同run/同窗口绑定、唯一sent与来源哈希、完整实际播放/免费奖励链及原证据路径、两行连续编号/间距/后继锁、独立通关勾和未知弹层优先。真实Runner专项核对只完成原故事、不重开入口，attempted/sent不变；另验证纯剧情active不能认领后续战斗/胜利/战斗结算。私有原画面仅在隔离状态副本做生产OCR回放，缺失则跳过；不恢复或修改实际旧进度，不提交账号素材，不向游戏发送测试输入。
