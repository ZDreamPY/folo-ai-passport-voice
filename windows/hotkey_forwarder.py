#!/usr/bin/env python3
"""热键+麦克风转发器: 把 AI Passport 设备变成"无线热键 + 无线麦克风"。

与 relay.py 的差异(架构见 passport-os/docs/voice-udp-channel.md):
  relay  = 收设备音频 → 火山 ASR → 注入文本(需要 ASR 密钥);
  本程序 = 收设备按键事件 → 注入系统热键(如右 Shift,调起语音输入法);
           收设备音频 → 解码 → 写虚拟声卡(VB-Cable),输入法把它当麦克风。
  不需要任何 ASR 密钥/账号 —— 识别由输入法自己完成。

设备「随身 AI 语音」按住 UP = voice.start + 音频流,松开 = voice.end。
本程序回报 pc.status 音频/热键配置就绪状态，设备据此允许按住说话。

用法:
  python companion/hotkey_forwarder.py                  # 读取配置；默认右Shift + hold
  python companion/hotkey_forwarder.py --mode hold      # 按住=热键按住
  python companion/hotkey_forwarder.py --key f9         # 换热键
  python companion/hotkey_forwarder.py --list-devices   # 列出声卡,找 CABLE
  python companion/hotkey_forwarder.py --no-audio       # 只做热键转发

虚拟声卡(麦克风路由): 需安装 VB-Audio Virtual Cable(https://vb-audio.com/Cable/),
安装后在语音输入法里把麦克风选为 "CABLE Output"。未安装时设备显示通道未就绪。
"""

import argparse
import asyncio
import ctypes
import json
import os
import queue
import sys
import threading
import time

# GitHub Windows runners and some legacy consoles default to cp1252.  Chinese
# status messages must never crash the forwarding loop or its release tests.
for _stream in (sys.stdout, sys.stderr):
    if getattr(_stream, "encoding", "").lower() not in ("utf-8", "utf8"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import adpcm
from udp_transport import UdpTransport, UdpError, EVENT_UUID, AUDIO_UUID

# ---------------------------------------------------------------------------
# Windows 按键注入(ctypes SendInput, 零第三方依赖)
# ---------------------------------------------------------------------------

VK_SCAN = {
    # name: (VK, 扫描码, extended)。扫描码为 PS/2 set-1。
    "right-shift": (0xA1, 0x36, False),
    "left-shift": (0xA0, 0x2A, False),
    "right-ctrl": (0xA3, 0x1D, True),
    "right-alt": (0xA5, 0x38, True),
    "f6": (0x75, 0x40, False),
    "f9": (0x78, 0x43, False),
    "f10": (0x79, 0x44, False),
}

# 完整键位表:在 VK_SCAN 基础上补全 F1-F12/字母/数字/常用键,支持组合键。
# 组合键写法 "win+h"、"ctrl+shift+space"(修饰键在前,普通键最后)。
_KEY_EXTRA = {
    "left-ctrl": (0xA2, 0x1D, False),
    "left-alt": (0xA4, 0x38, False),
    "left-win": (0x5B, 0x5B, True),
    "right-win": (0x5C, 0x5C, True),
    "caps": (0x14, 0x3A, False),
    "space": (0x20, 0x39, False),
    "enter": (0x0D, 0x1C, False),
    "tab": (0x09, 0x0F, False),
    "backspace": (0x08, 0x0E, False),
    "escape": (0x1B, 0x01, False),
}
for _i, _scan in enumerate([0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40,
                            0x41, 0x42, 0x43, 0x44, 0x57, 0x58]):
    _KEY_EXTRA[f"f{_i + 1}"] = (0x70 + _i, _scan, False)
for _ch, _scan in zip("qwertyuiopasdfghjklzxcvbnm",
                      [0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17,
                       0x18, 0x19, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23,
                       0x24, 0x25, 0x26, 0x2C, 0x2D, 0x2E, 0x2F, 0x30,
                       0x31, 0x32]):          # QWERTYUIOP ASDFGHJKL ZXCVBNM
    _KEY_EXTRA[_ch] = (0x41 + (ord(_ch) - 97), _scan, False)   # VK 'A'=0x41
for _i in range(10):
    _d = (_i + 1) % 10                         # '1','2',...,'9','0'
    _KEY_EXTRA[str(_d)] = (0x30 + _d, 0x02 + _i, False)
KEY_MAP = {**VK_SCAN, **_KEY_EXTRA}

# 组合键里的修饰键别名("win+h" 的 win = left-win)
MODIFIER_ALIASES = {"ctrl": "left-ctrl", "alt": "left-alt",
                    "shift": "left-shift", "win": "left-win"}
_MODIFIERS = {"left-ctrl", "right-ctrl", "left-alt", "right-alt",
              "left-shift", "right-shift", "left-win", "right-win"}


def resolve_key_spec(spec):
    """解析热键描述 → [(键名, VK, 扫描码, extended), ...]。

    单键 "right-shift"/"f9"/"h";组合键 "win+h"、"ctrl+shift+space"。
    组合键规则:非末位必须是修饰键;末位是修饰键时,整串必须全是修饰键
    (全修饰键"和弦",如微信输入法语音热键 ctrl+win —— 按住 Ctrl 再点 Win)。
    """
    parts = [p.strip().lower() for p in spec.split("+") if p.strip()]
    if not parts:
        raise ValueError("热键为空")
    keys = []
    for i, part in enumerate(parts):
        name = MODIFIER_ALIASES.get(part, part)
        if name not in KEY_MAP:
            raise ValueError(f"未知键名 '{part}'")
        if i < len(parts) - 1 and name not in _MODIFIERS:
            raise ValueError(f"组合键里 '{part}' 必须是修饰键(ctrl/alt/shift/win),且放在前面")
        keys.append((name,) + KEY_MAP[name])
    if len(parts) > 1 and MODIFIER_ALIASES.get(parts[-1], parts[-1]) in _MODIFIERS \
            and any(MODIFIER_ALIASES.get(p, p) not in _MODIFIERS for p in parts):
        raise ValueError("混合组合键最后一个必须是普通键;全修饰键组合(如 ctrl+win)才可全为修饰键")
    return keys


KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort),
                ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_void_p)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]   # 尺寸以 MOUSEINPUT 为准


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTUNION)]


def attach_to_default_desktop():
    """将当前线程挂接至用户交互桌面 WinSta0\Default(穿透沙箱桌面隔离)。"""
    if sys.platform == "win32":
        try:
            h_desk = ctypes.windll.user32.OpenDesktopW("Default", 0, False, 0x01FF)
            if h_desk:
                ctypes.windll.user32.SetThreadDesktop(h_desk)
        except Exception:
            pass


class _KeyWorker:
    def __init__(self):
        self._q = queue.Queue()
        self._thread = threading.Thread(target=self._run, name="key_worker", daemon=True)
        self._thread.start()

    def _run(self):
        attach_to_default_desktop()
        while True:
            fn, args = self._q.get()
            try:
                fn(*args)
            except Exception as e:
                print(f"[key] Worker error: {e}", file=sys.stderr)
            finally:
                self._q.task_done()

    def post(self, fn, *args):
        self._q.put((fn, args))
        self._q.join()


_worker = None


def _get_worker():
    global _worker
    if _worker is None:
        _worker = _KeyWorker()
    return _worker


def _do_send_key(vk, scan, extended, up):
    flags = (KEYEVENTF_SCANCODE if scan else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0) | (KEYEVENTF_KEYUP if up else 0)
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0,
                        dwExtraInfo=None)
    ret = ctypes.windll.user32.SendInput(1, ctypes.byref(inp),
                                         ctypes.sizeof(INPUT))
    if ret != 1:
        # SendInput 异常时降级走 keybd_event
        ctypes.windll.user32.keybd_event(vk & 0xFF, scan & 0xFF, flags, 0)


def _send_key(vk, scan, extended, up):
    _get_worker().post(_do_send_key, vk, scan, extended, up)


class KeyInjector:
    """热键注入器(支持单键及组合键,如 right-shift / win+h / ctrl+shift+space)。

    hold=设备按住UP说话期间热键保持按下,松开时抬起(适配"按住说话"类语音输入法,如讯飞/搜狗长按右Shift);
    tap=开启时点击热键(Down+60ms+Up),松开时再次点击以结束录音提交上屏(适配点击式语音键)。
    """

    def __init__(self, spec, mode):
        self.spec = spec
        self.mode = mode
        self._keys = resolve_key_spec(spec)   # [(键名, vk, scan, ext), ...]
        self._held = False
        self._active = False

    def start(self):
        attach_to_default_desktop()
        if self.mode == "hold":
            if not self._held:
                self._held = True
                for _name, vk, scan, ext in self._keys:
                    _send_key(vk, scan, ext, up=False)
                print(f"[key] {self.spec} 按下(hold, 开启语音输入)")
        else:
            if self._active:
                return
            self._active = True
            for _name, vk, scan, ext in self._keys:
                _send_key(vk, scan, ext, up=False)
            time.sleep(0.06)
            for _name, vk, scan, ext in reversed(self._keys):
                _send_key(vk, scan, ext, up=True)
            print(f"[key] {self.spec} 点击(tap, 开启语音输入)")

    def click(self):
        """发送单次按键点击(Down + 60ms + Up)，用于触发独立按键动作(如回车发送)。"""
        attach_to_default_desktop()
        for _name, vk, scan, ext in self._keys:
            _send_key(vk, scan, ext, up=False)
        time.sleep(0.06)
        for _name, vk, scan, ext in reversed(self._keys):
            _send_key(vk, scan, ext, up=True)
        print(f"[key] {self.spec} 点击(执行发送/确认)")

    def stop(self):
        attach_to_default_desktop()
        if self.mode == "hold" and self._held:
            self._held = False
            for _name, vk, scan, ext in reversed(self._keys):
                _send_key(vk, scan, ext, up=True)
            print(f"[key] {self.spec} 抬起(hold, 结束语音输入)")
        elif self.mode == "tap" and self._active:
            # 满足输入法"按下可开启语音输入，按任意键均可结束"：松开按键时再发一次点击以提交上屏
            self._active = False
            time.sleep(0.08)
            for _name, vk, scan, ext in self._keys:
                _send_key(vk, scan, ext, up=False)
            time.sleep(0.06)
            for _name, vk, scan, ext in reversed(self._keys):
                _send_key(vk, scan, ext, up=True)
            print(f"[key] {self.spec} 再次点击(tap, 结束语音输入)")


class AltTabChord:
    """迟滞式组合键(切窗多选): 首点=按住修饰键 + 点一次触发键,并开启迟滞窗;
    迟滞窗内再点=再点一次触发键(在候选窗口间移动);停止点按超过迟滞时长后
    松开修饰键 → 系统完成切换到当前选中窗口。
    单键键位(无修饰键,如 enter)退化为逐次点击。设备侧协议不变
    (仍是 key.action=alt_tab),迟滞完全由电脑端实现。
    """

    def __init__(self, spec, hysteresis=0.5):
        keys = resolve_key_spec(spec)          # 同时完成键位合法性校验
        self.spec = spec
        self.hysteresis = max(0.05, float(hysteresis))
        self._mods = keys[:-1] if len(keys) > 1 else []
        self._trigger = keys[-1]
        self._chording = False
        self._timer = None
        self._lock = threading.RLock()

    def active(self):
        with self._lock:
            return self._chording

    def press(self):
        """设备点按一次:首点按住修饰键+点触发键;迟滞窗内再点=再点触发键。"""
        with self._lock:
            first = not self._chording
            self._chording = True
            if first:
                for _n, vk, scan, ext in self._mods:
                    _send_key(vk, scan, ext, up=False)
            _name, vk, scan, ext = self._trigger
            _send_key(vk, scan, ext, up=False)
        time.sleep(0.05)
        _send_key(vk, scan, ext, up=True)
        if first:
            print(f"[key] {self.spec} 已按下并保持"
                  f"(迟滞 {int(self.hysteresis * 1000)}ms,连点选窗)")
        else:
            print("[key] 迟滞窗内再点一次(移动到下一个候选窗口)")
        self._rearm()

    def _rearm(self):
        with self._lock:
            if self._timer:
                self._timer.cancel()
            t = threading.Timer(self.hysteresis, self._release)
            t.daemon = True
            self._timer = t
        t.start()

    def _release(self):
        with self._lock:
            self._timer = None
            if not self._chording:
                return
            self._chording = False
            mods = list(self._mods)
        for _n, vk, scan, ext in reversed(mods):
            _send_key(vk, scan, ext, up=True)
        if mods:
            print("[key] 迟滞结束,松开修饰键 → 完成切窗")

    def cancel(self):
        """立即结束迟滞并抬键(语音开始/链路断开/配置切换时强制复位)。"""
        with self._lock:
            t, self._timer = self._timer, None
            was, self._chording = self._chording, False
            mods = list(self._mods)
        if t:
            t.cancel()
        if was:
            for _n, vk, scan, ext in reversed(mods):
                _send_key(vk, scan, ext, up=True)
            print("[key] 切窗迟滞被打断,修饰键已抬起")


def clamp_hysteresis_ms(v, fallback=1000):
    """迟滞时长(ms)归一化:非法回退,越界夹取 100–3000。

    默认 1s:实测 0.5s 窗口小于人的点按节奏(点击间隔普遍 >500ms),
    迟滞总在下次点击前超时,连点永远进不了"选窗"状态。"""
    try:
        ms = int(float(str(v).strip()))
    except (TypeError, ValueError):
        return fallback
    return max(100, min(3000, ms))


# ---------------------------------------------------------------------------
# 音频出口: 解码 ADPCM → 写虚拟声卡(VB-Cable 的 CABLE Input)
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000
FRAME_BYTES = 3200                      # 1600 样本 × int16
SILENCE = b"\x00" * FRAME_BYTES
ENTER_DEBOUNCE_SECONDS = 0.35


class AudioSink:
    """把设备音频块解码后按实时节奏写进虚拟声卡。

    独立写线程 + 有界队列: 写线程 stream.write 天然按实时节拍消费,
    队列只吸收 UDP 抖动;溢出丢最旧(保延迟,宁丢勿积)。
    """

    def __init__(self, device_substr, blocks_max=5):
        self.enabled = False
        self.device_name = None
        self._q = queue.Queue(maxsize=blocks_max)
        try:
            import sounddevice as sd
        except (ImportError, OSError) as e:
            print(f"[audio] sounddevice 不可用({e}),麦克风通道未就绪",
                  file=sys.stderr)
            return
        outputs = [(i, d["name"]) for i, d in enumerate(sd.query_devices())
                   if d["max_output_channels"] > 0
                   and device_substr.lower() in d["name"].lower()]
        if not outputs:
            print("[audio] 没找到虚拟声卡(含 '%s' 的播放设备)。\n"
                  "  请安装 VB-Audio Virtual Cable: https://vb-audio.com/Cable/\n"
                  "  安装后重新运行本程序,并在语音输入法里把麦克风选为 'CABLE Output'。\n"
                  "  硬件麦克风模式暂不可用。" % device_substr, file=sys.stderr)
            return
        # One Windows device can expose MME, DirectSound and WASAPI endpoints.
        # Try another matching endpoint if the first cannot open at 16 kHz.
        for idx, name in outputs:
            stream = None
            try:
                stream = sd.RawOutputStream(
                    samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                    device=idx, blocksize=0)
                stream.start()
                self._stream = stream
                self.device_name = name
                break
            except Exception as e:
                if stream is not None:
                    stream.close()
                print(f"[audio] 打开 [{idx}] '{name}' 失败: {e}", file=sys.stderr)
        else:
            return
        self.enabled = True
        threading.Thread(target=self._writer, name="audio_writer",
                         daemon=True).start()
        print(f"[audio] 麦克风路由就绪 → '{name}'"
              " (输入法里把麦克风选为对应的 'CABLE Output')")

    @staticmethod
    def _find_output(sd, substr):
        try:
            default_out = sd.default.output[1] if sd.default.output else -1
        except Exception:
            default_out = -1
        found = (None, None)
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] > 0 and substr.lower() in d["name"].lower():
                found = (i, d["name"])
                break
        if found[0] is None:
            return (None, None)
        _ = default_out
        return found

    def write_block(self, adpcm_block):
        """AUDIO 载荷 [seq][0x80]+804B → 解码入队。"""
        if not self.enabled:
            return
        try:
            samples = adpcm.decode_block(adpcm_block)
        except Exception as e:
            print(f"[audio] 解码失败: {e}", file=sys.stderr)
            return
        pcm = bytearray(len(samples) * 2)
        for i, v in enumerate(samples):
            v = max(-32768, min(32767, int(v)))
            pcm[i * 2] = v & 0xFF
            pcm[i * 2 + 1] = (v >> 8) & 0xFF
        try:
            self._q.put_nowait(bytes(pcm))
        except queue.Full:
            try:
                self._q.get_nowait()   # 丢最旧,保延迟
                self._q.task_done()
                self._q.put_nowait(bytes(pcm))
            except queue.Empty:
                pass

    def _writer(self):
        while True:
            queued = True
            try:
                data = self._q.get(timeout=0.2)
            except queue.Empty:
                queued = False
                data = SILENCE         # 空闲补零,维持实时节拍
            if not self.enabled:       # 已被 close()/重建:丢弃数据,线程空转待回收
                if queued:
                    self._q.task_done()
                continue
            try:
                self._stream.write(data)
            except Exception as e:
                self.enabled = False
                print(f"[audio] 写声卡失败: {e}", file=sys.stderr)
                self.clear()
                return
            finally:
                if queued:
                    self._q.task_done()

    def close(self):
        """停用并关闭声卡(热重载换设备时调用,写线程随后自行空转)。"""
        self.enabled = False
        self.clear()
        try:
            self._stream.close()
        except Exception:
            pass

    def clear(self):
        while True:
            try:
                self._q.get_nowait()
                self._q.task_done()
            except queue.Empty:
                return

    def drain(self, timeout=0.8):
        # Deliver the final buffered syllables before releasing the input-method key.
        deadline = time.monotonic() + timeout
        while self.enabled and self._q.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        if self._q.unfinished_tasks:
            self.clear()


# ---------------------------------------------------------------------------
# 事件/音频 handler + 主循环
# ---------------------------------------------------------------------------

class Forwarder:
    def __init__(self, args):
        self.args = args
        self.injector = KeyInjector(args.key, args.mode)
        # key.action 的键位可经 voice-config.json 的 key_actions 覆盖
        # (enter/alt_tab → 任意键位串;缺省:回车键,Alt+Tab 切窗)。
        actions = getattr(args, "key_actions", None) or {}
        self.enter_spec = str(actions.get("enter", "enter"))
        self.alt_tab_spec = str(actions.get("alt_tab", "alt+tab"))
        self.enter_injector = KeyInjector(self.enter_spec, "tap")
        # 切窗用迟滞 chord:首点按住 Alt 点 Tab,迟滞窗内连点选窗,停手完成切换
        self.hysteresis_ms = clamp_hysteresis_ms(
            getattr(args, "alt_tab_hysteresis_ms", None))
        self.alt_chord = AltTabChord(self.alt_tab_spec,
                                     self.hysteresis_ms / 1000.0)
        self.sink = None if args.no_audio else AudioSink(args.output_substr)
        self.audio_blocks = 0
        self.active = False
        self.last_audio_at = 0.0
        self.last_seq = None
        self.last_enter_at = float("-inf")
        self.last_alt_tab_at = float("-inf")
        self.reload_link = False   # 配置改了 IP/端口 → 状态协程触发重连

    def apply_config(self, cfg):
        """voice-config.json 变更后的热重载:换键位/动作/声卡,不重启进程。

        IP/端口变化只置 reload_link,状态协程会断开重建链路(定向 beacon 秒连)。
        录音进行中不切换语音热键与声卡,结束后下次保存再生效。
        """
        # 1. 语音热键(开始/结束听写的注入键)
        key = str(cfg.get("hotkey_key") or self.args.key)
        mode = str(cfg.get("hotkey_mode") or self.args.mode)
        if mode not in ("tap", "hold"):
            mode = self.args.mode
        if key != self.args.key or mode != self.args.mode:
            if self.active:
                print("[cfg] 录音中暂缓切换语音热键,本次录音结束后再保存生效")
            else:
                try:
                    self.injector = KeyInjector(key, mode)
                    self.args.key, self.args.mode = key, mode
                    print(f"[cfg] 语音热键已切换 → {key} ({mode})")
                except ValueError as e:
                    print(f"[cfg] 忽略非法语音热键 '{key}': {e}", file=sys.stderr)
        # 2. key.action 动作键位(回车 / 切窗迟滞)
        actions = cfg.get("key_actions") if isinstance(cfg.get("key_actions"), dict) else {}
        spec = str(actions.get("enter") or self.enter_spec)
        if spec != self.enter_spec:
            try:
                inj = KeyInjector(spec, "tap")
            except ValueError as e:
                print(f"[cfg] 忽略非法 enter 键位 '{spec}': {e}", file=sys.stderr)
            else:
                self.enter_spec = spec
                self.enter_injector = inj
                print(f"[cfg] enter 动作键位已切换 → {spec}")
        # 切窗:键位或迟滞时长任一变化都重建 chord(重建前强制抬键)
        spec = str(actions.get("alt_tab") or self.alt_tab_spec)
        ms = clamp_hysteresis_ms(cfg.get("alt_tab_hysteresis_ms"),
                                 self.hysteresis_ms)
        if spec != self.alt_tab_spec or ms != self.hysteresis_ms:
            try:
                chord = AltTabChord(spec, ms / 1000.0)
            except ValueError as e:
                print(f"[cfg] 忽略非法 alt_tab 键位 '{spec}': {e}", file=sys.stderr)
            else:
                self.alt_chord.cancel()
                self.alt_chord = chord
                self.alt_tab_spec, self.hysteresis_ms = spec, ms
                print(f"[cfg] 切窗键位已切换 → {spec}(迟滞 {ms}ms)")
        # 3. 虚拟声卡(录音中不重建)
        substr = str(cfg.get("output_substr") or "").strip()
        if substr and self.sink is not None and substr != self.args.output_substr:
            if self.active:
                print("[cfg] 录音中暂缓切换声卡,本次录音结束后再保存生效")
            else:
                self.args.output_substr = substr
                self.sink.close()
                self.sink = AudioSink(substr)
                print(f"[cfg] 音频输出设备已切换 → '{substr}'"
                      + ("" if self.sink.enabled else " (未就绪,检查设备名)"))
        # 4. 设备 IP / UDP 端口 → 触发链路重建
        new_ip = str(cfg.get("device_ip") or "").strip()
        if new_ip and new_ip != str(self.args.device_ip or "").strip():
            self.args.device_ip = new_ip
            self.reload_link = True
            print(f"[cfg] 设备目标 IP → {new_ip}(重连后生效)")
        try:
            new_port = int(str(cfg.get("udp_port") or "").strip())
        except (TypeError, ValueError):
            new_port = None
        if new_port and 0 < new_port < 65536 and new_port != self.args.port:
            self.args.port = new_port
            self.reload_link = True
            print(f"[cfg] UDP 端口 → {new_port}(重连后生效)")

    def pc_status(self):
        return {"type": "pc.status", "audioReady": bool(self.sink and self.sink.enabled),
                "hotkeyReady": bool(self.injector._keys)}

    def finish(self, drain=False):
        self.active = False
        try:
            if self.sink:
                if drain:
                    self.sink.drain()
                else:
                    self.sink.clear()
        finally:
            self.injector.stop()
            self.alt_chord.cancel()   # 迟滞中的 Alt 必须抬起,绝不悬空

    def check_health(self, now=None):
        now = time.monotonic() if now is None else now
        # PING can remain alive when voice.end is lost. Audio silence timeout,
        # independent of link heartbeat, ensures a held key still gets released.
        if self.active and (now - self.last_audio_at > 2.5 or
                            (self.sink is not None and not self.sink.enabled)):
            print("[link] 语音通道中断，停止传音并释放快捷键")
            self.finish()

    def _do_enter_action(self):
        now = time.monotonic()
        if now - self.last_enter_at < ENTER_DEBOUNCE_SECONDS:
            print("[evt] 忽略重复的回车动作")
            return
        self.last_enter_at = now

        # 设备侧按键既是注入,也是状态对账点:正常时 voice.end 已释放语音热键。
        # 若该 UDP 包丢失,固件已 READY 而 PC 仍以为在录音 —— 先结束残留语音
        # 状态再注入,绝不造成组合键污染(如 Shift+Enter)或输入法无限听写。
        stale_voice = self.active or self.injector._held or self.injector._active
        if stale_voice:
            print("[evt] 回车对账: 先结束残留语音状态")
        self.finish(drain=False)
        if stale_voice:
            time.sleep(0.05)
        self.enter_injector.click()

    def _do_alt_tab_action(self):
        # 首点做防抖+语音对账;迟滞窗内连点必须畅通,不做防抖
        if not self.alt_chord.active():
            now = time.monotonic()
            if now - self.last_alt_tab_at < ENTER_DEBOUNCE_SECONDS:
                print("[evt] 忽略重复的切窗动作")
                return
            self.last_alt_tab_at = now
            stale_voice = self.active or self.injector._held or self.injector._active
            if stale_voice:
                print("[evt] 切窗对账: 先结束残留语音状态")
            self.finish(drain=False)   # finish 内会复位尚未开始的 chord(no-op)
            if stale_voice:
                time.sleep(0.05)
        self.alt_chord.press()

    def on_event(self, payload):
        try:
            ev = json.loads(payload.decode("utf-8").strip())
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(ev, dict):
            return
        name = ev.get("event", "")
        if name == "voice.start":
            if self.active:
                return
            if self.sink is not None and not self.sink.enabled:
                return
            print("[evt] 设备开始说话(voice.start)")
            self.audio_blocks = 0
            self.last_seq = None
            self.last_audio_at = time.monotonic()
            if self.sink:
                self.sink.clear()
            self.injector.start()
            self.active = True
        elif name == "voice.end":
            print(f"[evt] 设备结束说话(voice.end),收到音频块={self.audio_blocks}")
            self.finish(drain=True)
        elif name == "device.hello":
            print("[evt] 设备上线(device.hello)")
        elif name == "key.action" and ev.get("action") == "enter":
            self._do_enter_action()
        elif name == "key.action" and ev.get("action") == "alt_tab":
            self._do_alt_tab_action()
        # status/agent.* 等其余事件与本程序无关,忽略

    def on_audio(self, payload):
        # 载荷 = [seq][0x80] + 804B ADPCM block;去掉 2B 帧头再解码
        # --no-audio 模式下电脑使用自己的麦克风，设备音频包直接丢弃。
        if self.active and len(payload) == 806 and payload[1] == 0x80:
            seq = payload[0]
            if self.last_seq is not None and not 0 < ((seq - self.last_seq) & 255) < 128:
                return
            self.last_seq = seq
            self.last_audio_at = time.monotonic()
            if self.sink is not None:
                self.sink.write_block(payload[2:])
            self.audio_blocks += 1
            if self.audio_blocks == 1:
                print("[audio] 已收到设备首个音频块并写入 VB-Cable")

    def on_disconnect(self):
        print("[link] 设备断开,热键复位;等待 beacon 自动重连...")
        self.finish()                 # 链路死了热键必须抬起来

    async def run(self):
        while True:
            transport = UdpTransport(port=self.args.port,
                                     device_wait_timeout=10 ** 9,
                                     device_ip=self.args.device_ip,
                                     auto_recover=False)
            status_task = None
            # 链路断开信号:on_disconnect 由读线程经 call_soon_threadsafe 在
            # 事件循环线程里调用,这里 set asyncio.Event 唤醒下方 wait。
            # 修(2026-09-13):原 `await asyncio.Event().wait()` 等的是永远没人
            # set 的匿名事件 —— 设备静默 6s 判定断开后读线程退出、beacon 照发,
            # 本协程却永远卡死 → forwarder 变成"会发 beacon 但聋了"的僵尸,
            # 再也收不到设备(实测复现)。
            link_down = asyncio.Event()

            def on_disconnect():
                self.on_disconnect()
                link_down.set()

            try:
                await transport.scan_for_device(None, None)
                await transport.connect("udp://",
                                        on_disconnect=on_disconnect)
                await transport.start_notify(EVENT_UUID, self.on_event)
                await transport.start_notify(AUDIO_UUID, self.on_audio)
                print("[link] 就绪: 等待设备按键/音频(设备上打开「AI语音」, "
                      "按住 UP 说话)")

                async def status():
                    last_status = 0.0
                    announced_status = None
                    while True:
                        if self.reload_link:   # 配置改了 IP/端口 → 断开重建链路
                            self.reload_link = False
                            print("[cfg] 应用新链路配置,重连中...")
                            link_down.set()
                            return
                        self.check_health()
                        now = time.monotonic()
                        if now - last_status >= 1.0:
                            last_status = now
                            try:
                                current_status = self.pc_status()
                                await transport.write_gatt_char(EVENT_UUID,
                                    (json.dumps(current_status) + "\n").encode())
                                if current_status != announced_status:
                                    announced_status = current_status
                                    print("[link] PC 就绪状态已发送: "
                                          f"audio={current_status['audioReady']} "
                                          f"hotkey={current_status['hotkeyReady']}")
                            except Exception as e:
                                print(f"[link] PC 状态回报失败: {e}",
                                      file=sys.stderr)
                                self.finish()
                                link_down.set()
                                return
                        await asyncio.sleep(0.2)

                status_task = asyncio.create_task(status())
                await link_down.wait()   # 直到链路断(on_disconnect 已 set)
                link_down.clear()
            except UdpError as e:
                print(f"[link] {e};10s 后重试", file=sys.stderr)
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                return
            finally:
                if status_task:
                    status_task.cancel()
                    try:
                        await status_task
                    except asyncio.CancelledError:
                        pass
                self.finish()
                try:
                    await transport.disconnect()
                except Exception:
                    pass
            await asyncio.sleep(0.5)


def get_config_path():
    """返回生效的 voice-config.json 路径(不存在则给缺省路径,供保存用)。"""
    base = os.path.dirname(sys.executable if getattr(sys, "frozen", False)
                           else os.path.abspath(__file__))
    for name in ("voice-config.json", "config.local.json"):
        path = os.path.join(base, name)
        if os.path.isfile(path):
            return path
    return os.path.join(base, "voice-config.json")


def load_local_config():
    """Portable config beside the executable/source; never needs the ASR GUI.

    Keep legacy config.local.json as a fallback for existing source users.
    Release packaging excludes both user configuration files.
    """
    path = get_config_path()
    try:
        with open(path, encoding="utf-8-sig") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def watch_config(fwd, path, interval=1.2):
    """后台线程:监视 voice-config.json 变更(mtime),变更即热重载。

    设置面板(托盘/网页)保存后无需重启转发器 —— 换键位/声卡立即生效,
    换 IP/端口会自动断开重连。
    """
    last = None
    while True:
        try:
            m = os.path.getmtime(path)
        except OSError:
            m = None
        if last is None:
            last = m
        elif m != last:
            last = m
            try:
                with open(path, encoding="utf-8-sig") as f:
                    cfg = json.load(f)
                if isinstance(cfg, dict):
                    fwd.apply_config(cfg)
            except Exception as e:
                print(f"[cfg] 配置重载失败: {e}", file=sys.stderr)
        time.sleep(interval)


def list_audio_devices():
    try:
        import sounddevice as sd
    except (ImportError, OSError) as e:
        print(f"sounddevice 不可用: {e}")
        return
    for i, d in enumerate(sd.query_devices()):
        kind = "播放" if d["max_output_channels"] > 0 else "录音"
        print(f"  [{i}] {kind} {d['name']}")
    print("提示: 找名字含 'CABLE Input' 的播放设备 = 虚拟声卡已安装。")


def main():
    cfg = load_local_config()
    default_key = str(cfg.get("hotkey_key") or "right-shift")
    default_mode = str(cfg.get("hotkey_mode") or "hold")

    ap = argparse.ArgumentParser(
        description="AI Passport 热键+麦克风转发器(配置见 voice-config.json, "
                    "命令行参数优先)")
    ap.add_argument("--key", default=default_key,
                    help="注入的热键: 单键(right-shift/f6/h/1...)或组合键"
                         "(win+h / ctrl+shift+space);缺省取配置 hotkey_key")
    ap.add_argument("--mode", default=default_mode,
                    choices=["tap", "hold"],
                    help="hold=长按式触发(按住说话，松手结束，推荐); "
                         "tap=点击式触发(按一次开启，再按一次结束)")
    ap.add_argument("--port", type=int,
                    default=int(cfg["udp_port"]) if str(cfg.get("udp_port") or "").strip().isdigit() else 33333)
    ap.add_argument("--output-substr",
                    default=str(cfg.get("output_substr") or "CABLE Input"),
                    help="虚拟声卡播放设备名包含的子串")
    ap.add_argument("--device-ip",
                    default=str(cfg.get("device_ip") or ""),
                    help="设备目标IP(如 192.168.5.6,防路由器AP隔离阻断广播)")
    ap.add_argument("--no-audio", action="store_true", help="只做热键转发")
    ap.add_argument("--list-keys", action="store_true",
                    help="列出全部可用键名后退出")
    ap.add_argument("--list-devices", action="store_true",
                    help="列出本机声卡后退出")
    ap.add_argument("--diagnose", action="store_true",
                    help="检查依赖、声卡与端口，不模拟按键、不录音")
    args = ap.parse_args()

    # key.action 键位映射(enter/alt_tab → 键位串),可在配置文件覆盖
    key_actions_cfg = cfg.get("key_actions")
    args.key_actions = key_actions_cfg if isinstance(key_actions_cfg, dict) else {}
    args.alt_tab_hysteresis_ms = cfg.get("alt_tab_hysteresis_ms", 1000)

    if args.diagnose:
        from diagnose_voice import main as diagnose
        raise SystemExit(diagnose())

    if args.list_keys:
        print("可用键名(组合键用 + 连接,如 win+h):")
        names = sorted(KEY_MAP)
        width = max(len(n) for n in names) + 2
        for i in range(0, len(names), 6):
            print("  " + "".join(n.ljust(width) for n in names[i:i + 6]))
        print("修饰键: ctrl/alt/shift/win (left-/right- 前缀区分左右)")
        return

    if args.list_devices:
        list_audio_devices()
        return

    try:
        resolve_key_spec(args.key)
        resolve_key_spec(str(args.key_actions.get("enter", "enter")))
        resolve_key_spec(str(args.key_actions.get("alt_tab", "alt+tab")))
    except ValueError as e:
        ap.error(f"{e};用 --list-keys 查看全部键名")

    fwd = Forwarder(args)
    threading.Thread(target=watch_config, args=(fwd, get_config_path()),
                     name="cfg_watch", daemon=True).start()
    print("=" * 66)
    print("           AI Passport · 随身 AI 语音服务已启动")
    print("=" * 66)
    print(" [使用说明]")
    print("   1. 硬件: 开机并连接同一 Wi-Fi(语音遥控器界面)")
    print("   2. 输入法: 语音识别麦克风选择 CABLE Output (VB-Audio)")
    print("   3. 说话: 鼠标点进电脑输入框，按住设备 UP 键说话，松手出字")
    print("   4. 单击 OK 发送回车；单击 DOWN 切窗,0.5s 内连点可选窗,停手即切换")
    print(" [提示] 保持此窗口开启即可使用；按 Ctrl+C 或关闭此窗口退出")
    print("=" * 66)
    print(f"热键: {args.key}  模式: {args.mode}  "
          f"音频: {'关闭' if args.no_audio else ('→ ' + fwd.sink.device_name if fwd.sink.enabled else '未就绪(装 VB-Cable 后重启本程序)')}")
    try:
        asyncio.run(fwd.run())
    except KeyboardInterrupt:
        print("\n退出")
        fwd.injector.stop()


if __name__ == "__main__":
    main()
