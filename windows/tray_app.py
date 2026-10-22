#!/usr/bin/env python3
"""AI Passport 语音遥控器 · 电脑端托盘入口。

双击托盘图标(或菜单"打开设置面板") → 浏览器打开本机设置页;
托盘负责托管转发器子进程(hotkey_forwarder.py),退出即全停。
开机自启由设置面板控制(写 HKCU Run,指向本脚本 --tray)。

用法:
  python tray_app.py            # 启动托盘 + 转发器,并打开设置面板
  python tray_app.py --tray     # 静默启动(开机自启用,不弹浏览器)
"""

import argparse
import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque

def app_dir():
    """应用目录:打包成 exe 后取 exe 所在目录(配置/日志跟随,便携使用);
    源码运行取脚本目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = app_dir()
sys.path.insert(0, BASE_DIR)

from settings_server import DEFAULT_PORT, make_server  # noqa: E402

FORWARDER = os.path.join(BASE_DIR, "hotkey_forwarder.py")
SETTINGS_URL = f"http://127.0.0.1:{DEFAULT_PORT}"
CREATE_NO_WINDOW = 0x08000000          # Windows: 子进程不弹控制台黑窗
LOG_LINES = 240


def make_icon_image():
    """托盘图标:暖橙小球 + 轮廓环眼 + 点阵笑(与设备端 EmoBall 同款)。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink = (14, 22, 32, 255)
    d.ellipse([4, 6, 60, 62], fill=(255, 169, 77, 255))
    d.ellipse([13, 19, 27, 37], outline=ink, width=3)      # 左眼环
    d.ellipse([37, 19, 51, 37], outline=ink, width=3)      # 右眼环
    d.ellipse([17, 25, 23, 31], fill=ink)                  # 瞳孔
    d.ellipse([41, 25, 47, 31], fill=ink)
    for x, y in ((22, 46), (28, 49), (36, 49), (42, 46)):  # 点阵笑
        d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=ink)
    return img


class TrayApp:
    def __init__(self):
        self.proc = None
        self.fwd_log_path = None
        self.lock = threading.Lock()
        self.log = deque(maxlen=LOG_LINES)
        self.server = None
        self.icon = None

    # ---------------- 转发器子进程 ----------------
    def _log(self, text):
        with self.lock:
            self.log.append(text)

    def start_forwarder(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return True
            self.fwd_log_path = None
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--forwarder"]   # exe 自带转发器入口
                # exe 转发器日志走文件(windowed 子进程没有可用 stdout)
                self.fwd_log_path = os.path.join(BASE_DIR, "forwarder.log")
                try:
                    open(self.fwd_log_path, "w", encoding="utf-8").close()
                except OSError:
                    self.fwd_log_path = None
            else:
                cmd = [sys.executable, "-u", FORWARDER]
            try:
                self.proc = subprocess.Popen(
                    cmd, cwd=BASE_DIR, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, creationflags=CREATE_NO_WINDOW,
                    bufsize=1, text=True, encoding="utf-8", errors="replace")
            except OSError as e:
                self._log(f"[tray] 转发器启动失败: {e}")
                return False
        self._log("[tray] 转发器已启动")
        if self.fwd_log_path:
            threading.Thread(target=self._pump_file, name="fw_out",
                             daemon=True).start()
        else:
            threading.Thread(target=self._pump_output, name="fw_out",
                             daemon=True).start()
        return True

    def _pump_file(self):
        """tail exe 转发器的 forwarder.log → 面板日志。"""
        proc, path = self.proc, self.fwd_log_path
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                while proc.poll() is None:
                    line = f.readline()
                    if line:
                        self._log(line.rstrip("\n"))
                    else:
                        time.sleep(0.2)
        except OSError:
            pass
        self._log(f"[tray] 转发器已退出(code={proc.returncode})")

    def _pump_output(self):
        proc = self.proc
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            self._log(line.rstrip("\n"))
        if proc.poll() is None:
            proc.wait()
        self._log(f"[tray] 转发器已退出(code={proc.returncode})")

    def stop_forwarder(self):
        with self.lock:
            proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()

    def restart_forwarder(self):
        self.stop_forwarder()
        return self.start_forwarder()

    def get_status(self):
        with self.lock:
            running = bool(self.proc and self.proc.poll() is None)
            tail = list(self.log)[-40:]
        return {"running": running, "log": "\n".join(tail)}

    # ---------------- 设置面板 ----------------
    def open_settings(self, icon=None, item=None):
        webbrowser.open(SETTINGS_URL)

    def _serve_settings(self):
        try:
            self.server = make_server(
                lambda: os.path.join(BASE_DIR, "voice-config.json"),
                get_status=self.get_status,
                restart=lambda: self.restart_forwarder())
        except OSError:
            # 端口被占(多半已有一个托盘在跑):直接打开既有面板
            self._log("[tray] 设置端口被占用,打开已运行实例的设置面板")
            self.open_settings()
            return
        self.server.serve_forever()

    # ---------------- 托盘 ----------------
    def on_quit(self, icon=None, item=None):
        if self.icon:
            self.icon.stop()

    def run(self, minimized=False):
        import pystray
        self.start_forwarder()
        threading.Thread(target=self._serve_settings, name="settings",
                         daemon=True).start()
        menu = pystray.Menu(
            pystray.MenuItem("打开设置面板", self.open_settings, default=True),
            pystray.MenuItem("重启转发器", lambda i, item: self.restart_forwarder()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", lambda i, item: self.on_quit()),
        )
        self.icon = pystray.Icon("AIPassportVoice", make_icon_image(),
                                 "AI Passport 语音遥控器", menu)
        if not minimized:
            self.open_settings()
        try:
            self.icon.run()
        finally:
            self.stop_forwarder()
            if self.server:
                self.server.shutdown()
            print("[tray] 已退出")


def _attach_forwarder_log():
    """exe 的 --forwarder 子进程是 --windowed GUI 程序,PyInstaller 会把
    stdout/stderr 换成丢弃内容的 NullWriter,print 全部消失。
    统一落到 exe 旁的 forwarder.log(行缓冲),由托盘 tail 进设置面板;
    返回日志路径,失败返回 None(面板日志只会少转发器输出,不影响功能)。"""
    try:
        path = os.path.join(app_dir(), "forwarder.log")
        f = open(path, "a", buffering=1, encoding="utf-8", errors="replace")
        sys.stdout = sys.stderr = f
        return path
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser(description="AI Passport 语音遥控器托盘")
    ap.add_argument("--tray", action="store_true",
                    help="静默启动(开机自启),不自动打开设置面板")
    ap.add_argument("--forwarder", action="store_true",
                    help=argparse.SUPPRESS)   # exe 内部:以转发器模式运行
    args = ap.parse_args()
    if args.forwarder:
        import hotkey_forwarder
        if getattr(sys, "frozen", False):
            _attach_forwarder_log()
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--forwarder"]
        hotkey_forwarder.main()
        return
    TrayApp().run(minimized=args.tray)


if __name__ == "__main__":
    main()
