# 来源和许可证

本仓库只覆盖随身语音应用。根 LICENSE 保留原有 MIT 声明，不表示提供整机其余代码或其授权。

- 基础语音实现：[zhaohuaxiaoy/folo-ai-passport-voice](https://github.com/zhaohuaxiaoy/folo-ai-passport-voice)，MIT；硬件基础参考 [FoloToy/ai-passport](https://github.com/FoloToy/ai-passport)，MIT。
- 本地应用生命周期、UDP/按键处理、Windows 适配和文档按根 LICENSE 分发。
- Windows 运行时涉及 Python、sounddevice、CFFI、PortAudio、PyInstaller、pystray、Pillow，随附原文在 `licenses/`；各自许可证仍适用。
- 设备端宿主使用 ESP-IDF、LVGL 等公开依赖时，应自行保留其许可证；本项目不打包这些库和维护者整机的共享实现。
- VB-CABLE 与语音输入法是各自厂商的软件，安装程序不随本包分发：`windows/install.cmd` 会在首次安装时自动从 VB-Audio 官网(vb-audio.com)下载驱动包并启动官方安装器，也可手动下载；VB-CABLE 为 Donationware，本仓库不修改、不再分发其安装包。

项目为社区作品，不代表 FoloToy、腾讯或 VB-Audio 官方支持。个人配置、录音和账号资料不属于公开内容。
