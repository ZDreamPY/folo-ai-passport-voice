# 用 Codex 辅助配置随身 AI 语音

Codex 可以帮助检查下载包、声卡、快捷键配置与端口，编辑转发器的 JSON，并定位连接问题。
需要使用**运行在这台 Windows 电脑上、能访问本地项目和终端的 Codex**。
只在远端执行的任务无法替你切换这台电脑的麦克风；系统界面操作还取决于当前可用的工具。

完整配置指令在 [GitHub 首页](../README.md#codex-setup)。先复制它，再按本文准备和验收。
不使用 Codex 也能照 [手动完整教程](QUICKSTART.zh-CN.md) 完成全部流程。

## 1. 先给 Codex 哪个文件夹

从 [Releases](https://github.com/ZDreamPY/folo-ai-passport-voice/releases) 下载最近发布的 **ai-passport-voice-app-*.zip**，全部解压。
在 Codex 中选择**解压后的完整目录**作为本地项目，让它能访问 docs 和 windows。

```text
你选择的解压目录/
├─ docs/                         使用教程
├─ windows/
│  ├─ AI-Passport-Voice.exe       可直接运行的电脑端
│  ├─ start.cmd                  日常启动
│  ├─ diagnose.cmd               手动诊断
│  ├─ voice-config.example.json  配置示例
│  └─ voice-config.json          根据你的快捷键创建；语音应用包不含个人配置
└─ device/                       本功能设备模块源码（不是可刷写固件）
```

如果选的是源码仓库，没有 EXE，先让它获取完整发布包；不要为了普通使用建立 Python 开发环境。
指令中的路径填实际解压目录，例如 `D:\AI-Passport-Voice`，不要把示例路径直接当成自己的路径。
未下载时也可让 Codex 从本项目 Releases 准备语音应用包。

## 2. 它能帮你处理什么

| 内容 | 处理方式 | 怎样确认 |
| --- | --- | --- |
| 语音应用包和启动入口 | 检查文件、确认下载来源 | windows 里有 EXE 和 start.cmd |
| 声卡与端口 | 调用程序的只读检查入口 | 枚举 CABLE 两端、查格式及端口 |
| VB-CABLE 安装准备 | 从官网获取、解压安装程序 | x64 安装程序与驱动文件在一起 |
| Windows 麦克风设置 | 有系统界面工具时协助；没有则给具体点击路径 | 默认输入为 CABLE Output |
| 输入法语音设置 | 通过原生设置界面核对，或让你提供实际键位/模式 | 实体键盘能开始并结束语音 |
| 映射 JSON | 备份已有文件、写入并校验配置 | 转发窗口热键/模式与输入法一致 |
| 启动与排错 | 启动一个转发器，区分网络/按键/声音问题 | 设备就绪、声音确实到达 |
| 实际识别 | 引导你对设备说话、检查输入框 | 记事本出字、松开结束、下键换行 |

管理员安装确认、重启以及开口说话需要你参与。
输入法登录、识别语言、隐私选项由你按其界面要求选择；不让 Codex 直接修改输入法 MMKV 或程序文件。
没有界面工具时，Codex 仍可完成文件和终端检查，再给你需要手动点击的步骤。

## 3. 应使用哪些诊断命令

下面在**语音应用包的 windows 目录**用 PowerShell 执行：

```powershell
.\AI-Passport-Voice.exe --list-keys
.\AI-Passport-Voice.exe --list-devices
.\AI-Passport-Voice.exe --diagnose
```

这些命令会结束，不会开始录音或模拟按键。自动执行时用 EXE，不用末尾会等待按键的 diagnose.cmd。
如果已经有自己的 start.cmd 窗口，诊断端口可能显示 BUSY；先识别该进程，关闭自己的窗口再检查。
当前诊断的端口检查为 UDP 33333。首次设置保留默认端口，勿让 Codex 通过随意换端口规避占用。

| 输出 | 表示什么 | 还缺什么验证 |
| --- | --- | --- |
| Shortcut syntax OK | 键名和模式合法 | 输入法是否设置为相同键位/模式 |
| UDP 33333 available | 检查时端口未被占用 | 设备与电脑能否互通 |
| UDP 33333 BUSY | 已有进程占用 | 是否自己的转发器正在运行 |
| Output format supported | 匹配的播放端格式可用，检测到 CABLE 录制端 | Windows 默认输入、输入法音源和实际收音 |
| Install VB-CABLE / Audio failure | 声卡缺失、格式或枚举失败 | 安装、重启、设备启用与具体错误 |

**诊断没有读出输入法设置，也没有做真实识别测试。** 不接受仅凭 OK 就宣布“已经能用了”的结论。

## 4. 配置文件怎样算正确

配置位置是 **windows/voice-config.json**，与 EXE 同目录。已有文件先备份，再改本次需要的字段。

```json
{
  "hotkey_key": "right-shift",
  "hotkey_mode": "hold",
  "output_substr": "CABLE Input",
  "udp_port": 33333,
  "device_ip": ""
}
```

这是转发器默认方案，需要输入法也支持并设置为右 Shift 按住说话。
左 Shift 改成 left-shift；点击切换型用 tap，但必须先验证同一快捷键能开始和结束。
具体键名与限制见 [映射键教程](QUICKSTART.zh-CN.md#mapping)。

Codex 应校验 JSON，再核对启动窗口的真实热键和模式。
命令行参数比 JSON 优先，修改后要重启自己的转发窗口。
不应添加不存在的 down_key 配置，或使用关闭音频的 --no-audio 来解决麦克风未就绪。

## 5. 安装重启后，复制什么继续

回到**同一个本地 Codex 项目**，补充实际完成的情况。下面的内容按事实修改后发送：

```text
继续配置 AI Passport 随身 AI 语音。
我刚完成 VB-CABLE 安装并重启。语音应用包仍在之前的解压目录，请重新检查声卡两端，不要直接重复安装。
请继续核对 Windows 默认输入为 CABLE Output，并完成输入法与转发器的语音快捷键匹配。
我在输入法里实际设置的是：右 Shift、按住说话。（请把这句改成你自己的设置）
如果端口占用，先判断是不是我自己的转发窗口；不要结束无关进程。
最后引导我用设备在记事本说话出字、松开结束、短按下键换行，分别记录结果。
```

如果设置窗口需要你操作，按 Codex 给出的步骤完成后，告诉它**实际选了什么**，而不是只说“已经设置”。
例如：“Windows 输入现在是 CABLE Output；输入法选左 Shift 长按；实体键盘可以打开和结束语音。”

## 6. 完成标准和以后怎么启动

以下都通过，才算完成：

- Windows 默认输入是 **CABLE Output**，输入法读取同一音源。
- 电脑实体语音快捷键能开始和结束；转发器的键位/模式一致。
- 转发器只有一个窗口，音频出口为 **CABLE Input**，设备显示可以说话。
- 按住设备上键，对设备说话后**记事本出现对应文字**；松开结束。
- 等识别完成，短按下键**记事本换行**。

以后双击 **windows/start.cmd**，设备进入随身语音，再点选目标输入框即可。
换过会议麦克风后，记得选回 CABLE Output。

配置结果中应分别注明“已自动完成”“由用户确认”“尚待验证”，不上传录音、Wi-Fi 密码或个人配置。
问题继续按 [故障排查](TROUBLESHOOTING.zh-CN.md) 定位。
