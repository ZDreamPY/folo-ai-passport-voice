# 随身语音验证边界

0.2.0 拆分发布时仅整理仓库和文档，未改变设备业务代码或 Windows 程序。0.3.0 在此基础上新增电脑端托盘与设置面板、设备端表情模块和 `install.cmd` 一键安装。独立项目不是新的整机固件版本。

## 历史集成验证（0.2.0 发布时记录）

在已验证的集成固件 `0.2.0-rc.6` 上，Windows EXE 与实机完成 3 轮按住上键、松开、下键测试：12 个系统注入键事件顺序正确，语音键释放 47–93 ms，Enter 16–47 ms。测试拦截键事件，未向用户当前窗口提交文字。这不是输入法识别准确率测试。

Windows 转发器 15 项单测覆盖 hold/tap、结束释放、残留状态对账、重复 Enter、音频失败回退等。设备纯状态机与界面数学通过 host 测试。新的应用目录再次独立运行这些测试；GitHub Actions 记录对应提交结果。

PC EXE 来自 Python 3.11.8、sounddevice 0.5.6、PyInstaller 6.20.0，源码与本项目 Windows 文件一致；EXE 的 `--help`、`--diagnose` 已检查。

## 0.3.0 新增部分的验证方式

- 设备端表情模块（`emo_ball`、`emo_anim`、`emo_map`）：映射与纯逻辑由 host 测试覆盖，host 测试共三个——`test_app_state`、`test_emo_map`、`test_ui_pixel_math`（`tools/test-host.sh` 编译运行）。真机渲染与动画效果不在 host 测试范围。
- 电脑端托盘、设置面板与热重载：Windows 单测覆盖配置校验、保存写回与热重载（`windows/tests/` 下 `test_hotkey_forwarder_unit.py`、`test_settings_and_reload.py` 等）；托盘菜单、开机自启等系统交互未列入自动化测试。
- `windows/install.cmd` 提供 VB-CABLE 自动安装流程：检测已装状态，未安装时从 VB-Audio 官网下载驱动包、解压并以管理员启动 `VBCABLE_Setup_x64.exe`，随后在有 Python 3.11 时安装依赖，并提示重启与选择 CABLE Output。脚本行为以仓库内 `install.cmd` 与 `install-cable.ps1` 为准。

**未验收：** 干净电脑上 install.cmd 全自动安装流程的实测、其他输入法/系统版本、真实字错误率、长时运行、用户自定义宿主的整机编译及音质。本仓库不分发整机 BIN，不宣称这里的模块可直接刷机。
