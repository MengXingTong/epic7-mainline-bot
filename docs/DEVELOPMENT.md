# 开发与发布检查

## CHANGELOG 维护

每次功能、安全保护、兼容性或发布行为发生变化，都同步编辑根目录 `CHANGELOG.md` 的 `Unreleased`。根据内容使用 Added / Changed / Fixed / Safety / Documentation / Verified / Known limitations 小节；仅记录真实存在的行为与实际执行的验证。发布时再整理版本号和日期，不能提前宣布未经验证的 PC 支持。

## 本地回归

需要 Windows x64 和 Python 3.12。安装器先直连获取依赖，失败后才回退原代理配置，不改变全局代理。

```powershell
py -3.12 install_dependencies.py
py -3.12 -B -X utf8 -m unittest discover -s tests -v
```

公开源码不分发真实账号截图素材，因此相关用例会明确标记 skipped。本机完整回归可通过环境变量 `EPIC7_PRIVATE_FIXTURES` 指向自己的私有素材目录。不要把该目录或变量的个人绝对路径提交到仓库。

单元测试不得产生游戏输入；模拟 ADB、输入、持久化，临时文件使用隔离目录。实机验证必须先核对目标账号/服务器，不用旧关或曾失败的关卡反复测试。

## 提交 / 发布前

1. `git diff --check`；检查暂存文件与完整历史，不含账号状态、截图、OCR、日志、设备配置、凭据或下载的第三方运行库。
2. 运行离线测试，分别报告通过、跳过和未验证的实机链路；不要把 skipped 当作 passed。
3. 更新 CHANGELOG、README 与对应兼容性说明，使声明与实测状态一致。
4. 推送优先临时绕开代理，直连失败后才尝试原代理；不要改用户全局代理设置。
5. 检查远端提交与 GitHub Actions 结果。源码 ZIP 从已提交 Git 文件生成，不从含账号数据的运行目录整目录压缩。

默认不创建新的外部发布、Release、tag 或上传大型离线运行库，除非用户要求。
