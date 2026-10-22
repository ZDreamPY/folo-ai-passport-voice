# AI Passport 随身语音

按住设备上键说话，松开结束识别，核对文字后短按中键回车（长按中键可重新配网）。这个项目把 AI Passport 用作 Windows 的无线麦克风与语音快捷键，文字识别由微信输入法等软件完成。

**本仓库只开源随身语音功能，不含整机源码或可刷写固件。** 固件由维护者在 [FoloToy 口袋百宝箱玩法页面](https://ai-passport.folotoy.cn/plays/438/) 发布。该页面若暂未提供包含随身语音的版本，请等待更新；不要把本仓库 Source code ZIP 当固件。

## 普通用户从这里开始

1. 使用同款 ESP32-C3 / 8 MB / ES8311 的 FoloToy AI Passport，从官网玩法页刷入包含“随身语音”的固件；已安装者跳过。
2. 在 [本项目 Releases](https://github.com/ZDreamPY/folo-ai-passport-voice/releases) 下载 `ai-passport-voice-app-0.3.0.zip`。这个应用包包含 Windows EXE、本功能源码和教程，**没有整机 BIN**。
3. 双击 `windows/install.cmd`：自动从官网安装 VB-CABLE 虚拟声卡（需管理员并重启一次）和 Python 依赖。
4. 重启后双击 `windows/start.cmd` 启动托盘，在设置面板完成快捷键与音频配置（详见[使用教程](docs/QUICKSTART.zh-CN.md)），然后完成记事本验收。

需要 Windows 10/11 x64、数据 USB 线、2.4 GHz Wi-Fi、VB-CABLE 和支持语音快捷键的输入法。电脑和设备在同一可互通局域网；USB 不会自动把设备变成 USB 麦克风，不需要蓝牙配对。

音频方向：设备麦克风 → Wi-Fi UDP → 电脑转发器 → **CABLE Input** → **CABLE Output** → 输入法。输入法的麦克风选 CABLE Output，扬声器仍用自己的设备。

### 按键与首次验收

- 点按上键：开启语音；等输入法界面出现后再说话。再点一次：结束识别（按住说话模式可在设置面板切换）。
- 等文字出现并核对。
- 点按 OK 键：发送 Enter；当前软件决定它是换行还是发送消息。先在记事本试，不要在重要聊天窗口直接测试。
- 点按下键：切换窗口——首点按住 Alt 点 Tab 开始选窗，迟滞时间内（默认 1 秒）继续点按可在多个窗口间移动选择，停手即落到当前选中窗口。
- 长按确定：退出设备应用。

### 设置面板

托盘图标双击（或菜单“打开设置面板”）打开 `http://127.0.0.1:38765`：语音热键点击录入（含 Ctrl+Win、Alt+Tab 系统组合）、触发方式、按键动作、切窗迟滞时长、音频输出设备、UDP 端口、设备 IP 与开机自启，保存即热生效。未安装 VB-CABLE 时面板顶部会显示红色提醒。输入法的快捷键与面板中“语音热键”必须一致。电脑诊断通过不等于输入法真实识别已验收。

## 源码边界

| 目录 | 内容 |
| --- | --- |
| `windows/` | 可运行的 Windows 转发器、ADPCM 解码、UDP 通道、诊断与测试 |
| `device/main/apps/voice/` | 本功能的设备端状态机、协议、录音生命周期、传输和界面业务代码 |
| `device/tests/` | 语音状态机和界面数学的可独立运行测试 |
| `docs/` | 使用、排错、固件入口、开发与底层接口适配说明 |

不包含首页/名片、收音机、小智、游戏、秒表、整机启动器、设置页、BSP 实现、共享字体或整机历史。设备端是**功能模块源码**，不是单独可刷写的 ESP-IDF 工程；开发者需按 [适配说明](docs/PORTING.zh-CN.md) 提供宿主接口。Windows 程序与纯逻辑测试可独立运行。

## 文档

- [详细使用教程](docs/QUICKSTART.zh-CN.md)
- [常见故障排查](docs/TROUBLESHOOTING.zh-CN.md)
- [官网固件与刷写注意](docs/FIRMWARE.zh-CN.md)
- [源码运行与测试](docs/DEVELOPMENT.zh-CN.md)
- [验证记录及限制](docs/VALIDATION.md)
- [第三方来源](THIRD_PARTY_NOTICES.md)

<a id="codex-setup"></a>
## 让本地 Codex 帮忙配置

在解压后的应用包目录打开本地 Codex，复制：

```text
先阅读 README.md 和 docs/QUICKSTART.zh-CN.md。只帮助我配置随身语音电脑端，不要重建或公开整机源码。固件从官网玩法页获取，不要把 Source code ZIP 当固件。
先运行 windows/install.cmd 自动安装 VB-CABLE 与依赖（已安装则跳过），然后启动 windows/start.cmd 打开设置面板，核对 VB-CABLE 两端、UDP 33333 和快捷键。已有配置先备份；我的输入法开始/结束快捷键和 tap/hold 模式需要在面板里按真实设置核对。
修改默认麦克风、安装驱动或开放防火墙前说明影响。不要关闭整套防火墙，也不要把系统声音输出改成 CABLE Input。
最后让我在记事本亲自说话，确认点按开始/再点结束、文字出现、下键切窗。未实际验证的环节明确说明，不自动把环境声音发到云端。
```

详见 [辅助配置说明](docs/CODEX_SETUP.zh-CN.md)。个人配置、录音与输入法账号不要提交到 GitHub。本项目不提供识别账号或 ASR 服务，也不承诺所有输入法版本兼容。
