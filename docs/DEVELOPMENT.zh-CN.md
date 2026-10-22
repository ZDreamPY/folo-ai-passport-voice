# 随身语音开发与测试

本仓库只包含本功能的代码。普通用户按 [使用教程](QUICKSTART.zh-CN.md) 使用 EXE；设备固件到官网获取。本仓库不含整机入口、BSP、共享 UI 或其他应用，不提供整机 `idf.py build`。

## Windows 安装脚本与源码运行

`windows/install.cmd` 是一键安装入口，做两件事：

- **自动安装 VB-CABLE**：先用 sounddevice 枚举输出设备名里是否含 CABLE，再用 WMI 查询声音设备名里是否含 VB-Audio；已安装则跳过。未安装时调用 `windows/install-cable.ps1`，从 [VB-Audio 官网](https://vb-audio.com/Cable/) 下载官方驱动包，解压到临时目录后以管理员权限启动 `VBCABLE_Setup_x64.exe`（脚本不分发驱动，只从官方地址获取），并提示装完重启、把输入法识别麦克风选为 CABLE Output。自动下载失败时脚本打印手动下载入口。
- **安装 Python 依赖**：检测到 Python 3.11 时创建 `.venv` 并 `pip install -r requirements.txt`（sounddevice、pystray、Pillow，即托盘 + 设置面板 + 转发器的完整依赖）；没有 Python 时跳过，EXE 双击使用不需要 Python。

开发者从源码运行转发器时，在仓库根目录打开 PowerShell，准备 Python 3.11 x64：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r windows\requirements-hotkey.txt
.\.venv\Scripts\python.exe windows\hotkey_forwarder.py --diagnose
.\.venv\Scripts\python.exe windows\hotkey_forwarder.py
```

`requirements-hotkey.txt` 只含转发器所需的最小依赖；要连托盘和设置面板一起跑，安装 `requirements.txt` 后运行 `windows\tray_app.py`。

先装好 VB-CABLE（可直接运行 install.cmd）、按教程设置输入法和可信局域网。配置保存在 `windows/voice-config.json`（仓库提供 `voice-config.example.json` 样例），核对路径与快捷键。不要同时运行源码版与 EXE 争用 UDP 33333。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s windows\tests -p "test_*.py" -v
```

Windows 单测覆盖转发器的 hold/tap、结束释放、残留状态对账、音频失败回退，以及设置面板的配置校验、保存与热重载（见 `windows/tests/` 下的 `test_hotkey_forwarder_unit.py`、`test_settings_and_reload.py` 等）。

## 托盘与设置面板

`windows/start.cmd` 优先启动 `AI-Passport-Voice.exe`；没有 EXE 时回落到 `.venv` 的 Python。源码形态的入口是 `windows/tray_app.py`（pystray 托盘）：启动转发器子进程与设置面板服务，托盘菜单可打开面板、重启转发器或退出。

设置面板由 `windows/settings_server.py` 提供，监听 **http://127.0.0.1:38765**，页面覆盖语音热键（点击录制）、触发方式 tap/hold、按键动作（OK 键发送、下键切窗与 100–3000 毫秒切窗迟滞 `alt_tab_hysteresis_ms`，默认 1000）、音频输出设备下拉、设备 IP / UDP 端口和开机自启（写 HKCU Run，无需管理员）。保存时经白名单校验后**原子写回** `voice-config.json`；转发器监视该文件的 mtime，变更即热重载键位、动作与声卡，设备 IP/端口变化则断开重建连接，无需重启进程。

发布的 EXE 与这里的 Windows 源码保持同一套实现，托盘依赖一并打包；驱动和输入法不打包。构建 EXE：`pip install pyinstaller` 后运行 `windows\build-exe.cmd`（缺 `icon.ico` 时自动用 `make_icon.py` 生成）。发布应用包：确认 `windows/AI-Passport-Voice.exe` 已构建，然后从仓库根目录运行 `powershell -NoProfile -ExecutionPolicy Bypass -File tools/make-release.ps1 -Version 0.3.0`，生成 `ai-passport-voice-app-<版本>.zip`（git 干净导出 + 注入 EXE）与 `.sha256` 校验文件。

## 设备纯逻辑测试

在 Linux、WSL 或具备 Bash、C 编译器的环境中，从仓库根目录运行：

```bash
bash tools/test-host.sh
```

脚本直接编译并运行三个纯逻辑测试：`device/tests/test_app_state.c`（配 `device/main/apps/voice/app_state.c` 状态机）、`device/tests/test_emo_map.c`（配 `emo_map.c` 表情映射）、`device/tests/test_ui_pixel_math.c`（配 `ui_pixel_math.c` 界面数学），不需要 ESP-IDF、私有仓库或设备。它覆盖长按/松开、电脑就绪、下键、重复事件、超时与故障分支，以及表情映射规则，不替代实机音频测试。

## 设备代码移植

状态机、协议与传输等核心源码来源于已验证固件的 Voice 应用目录，算法未为拆分改写；0.3.0 新增 `emo_ball`、`emo_anim`、`emo_map` 表情模块，`assets.bin` 表情资源可选，缺失时自动回退程序内置动画。应用模块依赖 ESP-IDF 5.5.3、FreeRTOS、LVGL 9.5，以及由宿主实现的硬件和 UI 接口。详细边界见 [PORTING](PORTING.zh-CN.md)。

如想在自己的固件集成，先接入纯状态机与协议，再提供录音、UDP、按键和显示生命周期；表情模块同样通过宿主提供的显示接口绘制。不要把缺少的整机文件从私有仓库复制进公开 PR；新增适配实现需独立审查发布范围。
