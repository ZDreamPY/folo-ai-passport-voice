#!/usr/bin/env python3
"""AI Passport 语音遥控器 · 本机设置面板(纯标准库 HTTP 服务 + 单页设置界面)。

托盘(tray_app.py)启动本服务并托管转发器子进程;浏览器打开 http://127.0.0.1:38765
即可改快捷键/动作键位/设备 IP/声卡/开机自启,保存写回 voice-config.json,
转发器经 mtime 监视热重载,即存即生效,无需重启、无需改代码。

单独运行(调试): python settings_server.py   # 只开设置页,不管转发器
"""

import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from hotkey_forwarder import resolve_key_spec  # noqa: E402  复用键位校验

DEFAULT_PORT = 38765   # 冷门端口;8765 等常被本机其他开发工具占用
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "AIPassportVoice"

# 允许写回 voice-config.json 的键(白名单,其余忽略防注入)
KNOWN_KEYS = {"hotkey_key", "hotkey_mode", "key_actions", "output_substr",
              "udp_port", "device_ip", "alt_tab_hysteresis_ms"}


# ---------------------------------------------------------------------------
# 配置读写与校验(纯逻辑,可单测)
# ---------------------------------------------------------------------------

def default_config():
    return {"hotkey_key": "ctrl+win", "hotkey_mode": "tap",
            "key_actions": {"enter": "enter", "alt_tab": "alt+tab"},
            "output_substr": "CABLE Input", "udp_port": 33333,
            "device_ip": "", "alt_tab_hysteresis_ms": 1000}


def validate_config(new_cfg, old_cfg):
    """校验并归一化用户提交的配置 → (clean_cfg, errors[])。

    只收白名单键;键位串过 resolve_key_spec;端口/IP/迟滞做基本合法性检查;
    非法字段保留旧值(部分保存,不整单拒绝)。缺省字段补默认值。
    """
    clean = {**default_config(),
             **(dict(old_cfg) if isinstance(old_cfg, dict) else {})}
    errors = []

    def merge(dst, src):
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                merge(dst[k], v)
            else:
                dst[k] = v

    merge(clean, {k: v for k, v in new_cfg.items() if k in KNOWN_KEYS})

    # 键位校验(语音热键 + 两个动作键位)
    try:
        resolve_key_spec(str(clean.get("hotkey_key") or ""))
    except ValueError as e:
        errors.append(f"语音热键: {e}")
        clean["hotkey_key"] = old_cfg.get("hotkey_key", "ctrl+win")
    actions = clean.get("key_actions")
    if not isinstance(actions, dict):
        actions = {}
        clean["key_actions"] = actions
    for name, fallback in (("enter", "enter"), ("alt_tab", "alt+tab")):
        spec = str(actions.get(name) or fallback)
        try:
            resolve_key_spec(spec)
            actions[name] = spec
        except ValueError as e:
            errors.append(f"{name} 动作键位: {e}")
            actions[name] = old_cfg.get("key_actions", {}).get(name, fallback)
    # 模式
    if clean.get("hotkey_mode") not in ("tap", "hold"):
        clean["hotkey_mode"] = "tap"
    # 切窗迟滞(毫秒,100–3000)
    try:
        ms = int(float(str(clean.get("alt_tab_hysteresis_ms")).strip()))
        if not 100 <= ms <= 3000:
            raise ValueError
        clean["alt_tab_hysteresis_ms"] = ms
    except (TypeError, ValueError):
        errors.append("切窗迟滞非法: "
                      f"{clean.get('alt_tab_hysteresis_ms')}(取 100–3000)")
        clean["alt_tab_hysteresis_ms"] = old_cfg.get("alt_tab_hysteresis_ms", 1000) \
            if isinstance(old_cfg, dict) else 1000
    # 端口
    try:
        port = int(str(clean.get("udp_port")).strip())
        if not 0 < port < 65536:
            raise ValueError
        clean["udp_port"] = port
    except (TypeError, ValueError):
        errors.append(f"UDP 端口非法: {clean.get('udp_port')}")
        clean["udp_port"] = old_cfg.get("udp_port", 33333)
    # 设备 IP(允许空 = 广播模式)
    ip = str(clean.get("device_ip") or "").strip()
    if ip:
        parts = ip.split(".")
        ok = len(parts) == 4
        if ok:
            try:
                ok = all(0 <= int(p) <= 255 for p in parts)
            except ValueError:
                ok = False
        if not ok:
            errors.append(f"设备 IP 非法: {ip}(留空则用广播)")
            ip = str(old_cfg.get("device_ip") or "")
    clean["device_ip"] = ip
    # 声卡子串
    clean["output_substr"] = str(clean.get("output_substr") or "CABLE Input").strip() \
        or "CABLE Input"
    return clean, errors


def load_config(config_path):
    try:
        with open(config_path, encoding="utf-8-sig") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            clean, _ = validate_config(cfg, {})
            clean.update({k: v for k, v in cfg.items() if k in KNOWN_KEYS})
            return clean
    except Exception:
        pass
    return default_config()


def save_config(config_path, cfg):
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, config_path)   # 原子替换,mtime 变化触发转发器热重载


# ---------------------------------------------------------------------------
# 开机自启(HKCU Run 注册表,无需管理员)
# ---------------------------------------------------------------------------

def _autostart_command():
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    python = sys.executable
    pythonw = os.path.join(os.path.dirname(python), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = python
    return f'"{pythonw}" "{os.path.join(BASE_DIR, "tray_app.py")}" --tray'


def is_autostart_on():
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, AUTOSTART_NAME)
            return True
    except OSError:
        return False


def set_autostart(on):
    if sys.platform != "win32":
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                        winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, AUTOSTART_NAME, 0, winreg.REG_SZ,
                              _autostart_command())
        else:
            try:
                winreg.DeleteValue(k, AUTOSTART_NAME)
            except FileNotFoundError:
                pass


# ---------------------------------------------------------------------------
# 声卡列表
# ---------------------------------------------------------------------------

def list_output_devices():
    """返回 (输出设备名列表, 是否发现虚拟声卡)。"""
    try:
        import sounddevice as sd
    except (ImportError, OSError):
        return [], False
    names, cable = [], False
    try:
        for d in sd.query_devices():
            if d["max_output_channels"] > 0:
                names.append(d["name"])
                if "cable" in d["name"].lower():
                    cable = True
    except Exception:
        pass
    return names, cable


# ---------------------------------------------------------------------------
# 设置页(单文件,无依赖;深色 + 暖橙,与设备端 UI 同一视觉系统)
# ---------------------------------------------------------------------------

PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Passport 语音遥控器 · 设置</title>
<style>
:root{--bg:#0E1620;--card:#182530;--ink:#E8F1F2;--dim:#7B8A94;
--accent:#FFA94D;--accent2:#FF6B81;--ok:#4CC9F0;--warn:#E8564F;--r:16px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,
"Segoe UI","Microsoft YaHei",sans-serif;padding:28px 16px 60px}
.wrap{max-width:680px;margin:0 auto}
h1{font-size:20px;font-weight:700;display:flex;align-items:center;gap:10px}
.dot{width:12px;height:12px;border-radius:50%;background:var(--warn);
display:inline-block;transition:background .3s}
.dot.on{background:#35d07f;box-shadow:0 0 8px #35d07f88}
.sub{color:var(--dim);font-size:13px;margin:4px 0 22px}
.card{background:var(--card);border-radius:var(--r);padding:18px 20px;
margin-bottom:14px}
.card h2{font-size:15px;font-weight:600;margin-bottom:4px}
.card p.tip{color:var(--dim);font-size:12.5px;margin-bottom:12px}
.row{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
label.f{display:block;font-size:12.5px;color:var(--dim);margin:10px 0 4px}
input[type=text],input[type=number],select{width:100%;background:#0E1620;
border:1px solid #2A3A48;border-radius:12px;color:var(--ink);
padding:10px 14px;font-size:15px;outline:none;transition:border .2s}
input:focus,select:focus{border-color:var(--accent)}
.hk{font-family:Consolas,monospace;letter-spacing:1px;text-align:center;
cursor:pointer;user-select:none}
.hk.rec{border-color:var(--accent);color:var(--accent);
animation:pulse 1s infinite}
@keyframes pulse{50%{opacity:.55}}
.hkrow{display:flex;gap:8px}
.hkrow .hk{flex:1;min-width:0}
.mini{flex:none;border:1px solid #2A3A48;background:transparent;
color:var(--dim);border-radius:12px;padding:0 14px;cursor:pointer;
font-size:12.5px;transition:color .2s,border-color .2s}
.mini:hover{color:var(--accent);border-color:var(--accent)}
.radio{display:flex;gap:0;border:1px solid #2A3A48;border-radius:12px;
overflow:hidden}
.radio button{flex:1;background:transparent;border:0;color:var(--dim);
padding:9px 0;cursor:pointer;font-size:14px}
.radio button.on{background:var(--accent);color:#1A1205;font-weight:600}
.btn{border:0;border-radius:999px;padding:11px 26px;font-size:15px;
cursor:pointer;font-weight:600}
.btn.primary{background:var(--accent);color:#1A1205}
.btn.primary:hover{filter:brightness(1.08)}
.btn.ghost{background:transparent;border:1px solid #2A3A48;color:var(--dim)}
.btn.ghost:hover{color:var(--ink);border-color:var(--dim)}
.save{position:sticky;bottom:14px;display:flex;justify-content:center;
margin-top:18px}
.save .btn{box-shadow:0 6px 20px #0008}
#toast{position:fixed;left:50%;bottom:84px;transform:translateX(-50%);
background:#223242;color:var(--ink);border-radius:999px;
padding:10px 22px;font-size:14px;opacity:0;transition:opacity .25s;
pointer-events:none;z-index:9}
#toast.show{opacity:1}
#toast.err{background:var(--warn);color:#fff}
pre{background:#0B131B;border-radius:12px;padding:12px;color:#9FB3BF;
font-size:12px;max-height:170px;overflow:auto;white-space:pre-wrap}
.chk{display:flex;align-items:center;gap:10px;cursor:pointer}
.chk input{width:18px;height:18px;accent-color:var(--accent)}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:560px){.grid2{grid-template-columns:1fr}}
</style></head><body><div class="wrap">
<h1><span class="dot" id="st-dot"></span>AI Passport 语音遥控器</h1>
<p class="sub">电脑端设置 · 保存后即时生效,无需重启</p>

<div class="card">
<h2>语音热键</h2>
<p class="tip">上键说话时电脑注入的快捷键(调起语音输入法)。
点输入框后直接按组合键录制;Ctrl+Win 需按住 Ctrl 再点 Win;
Alt+Tab 这类系统级组合会在窗口被切走时自动识别;点「默认」恢复。</p>
<div class="grid2">
<div><label class="f">热键</label>
<div class="hkrow"><input type="text" id="hotkey_key" class="hk" readonly
placeholder="点击录制"><button class="mini" id="def_hotkey">默认</button></div></div>
<div><label class="f">触发方式</label>
<div class="radio" id="hotkey_mode">
<button data-v="tap">点按开始/再点结束</button>
<button data-v="hold">按住说话</button></div></div>
</div></div>

<div class="card">
<h2>按键动作</h2>
<p class="tip">遥控器另外两个键在电脑端触发的键位,同样点击录制。</p>
<div class="grid2">
<div><label class="f">OK 键(发送)</label>
<div class="hkrow"><input type="text" id="act_enter" class="hk" readonly
placeholder="点击录制"><button class="mini" id="def_enter">默认</button></div></div>
<div><label class="f">下键(切窗)</label>
<div class="hkrow"><input type="text" id="act_alt_tab" class="hk" readonly
placeholder="点击录制"><button class="mini" id="def_alt_tab">默认</button></div></div>
</div>
<label class="f">切窗迟滞(毫秒,100–3000):首点切窗后在该时长内再按可多选窗口,停手后完成切换</label>
<input type="number" id="hysteresis_ms" min="100" max="3000" step="50"></div>

<div class="card">
<h2>设备连接</h2>
<div class="grid2">
<div><label class="f">设备 IP(留空用广播;路由器拦广播时必填)</label>
<input type="text" id="device_ip" placeholder="如 192.168.31.172"></div>
<div><label class="f">UDP 端口</label>
<input type="number" id="udp_port"></div></div></div>

<div class="card">
<h2>语音通道(虚拟声卡)</h2>
<div id="cable-warn" style="display:none;background:#3A1E1E;border:1px solid
var(--warn);border-radius:12px;padding:10px 14px;margin-bottom:12px;
font-size:13px;line-height:1.6">
未检测到 VB-CABLE 虚拟声卡, 设备语音无法进入输入法。<br>
运行解压目录里的 <b>install.cmd</b> 自动安装(需管理员+重启一次),
或到 <a href="https://vb-audio.com/Cable/" style="color:var(--accent)">vb-audio.com/Cable</a> 手动下载;
装完重启后, 在语音输入法里把识别麦克风选为 <b>CABLE Output</b>。</div>
<p class="tip">设备音频写入的播放设备;输入法的识别麦克风请选对应的
"CABLE Output"。未装 VB-Cable 时此通道不可用。</p>
<label class="f">音频输出设备</label>
<select id="output_substr"></select>
</div>

<div class="card">
<h2>启动</h2>
<label class="chk"><input type="checkbox" id="autostart">
开机自动启动(托盘常驻 + 转发器)</label>
<div class="row" style="margin-top:14px">
<button class="btn ghost" id="restart">重启转发器</button>
<span style="color:var(--dim);font-size:12.5px" id="fw-state"></span>
</div></div>

<div class="card">
<h2>运行日志</h2>
<pre id="log">…</pre></div>

<div class="save"><button class="btn primary" id="save">保存设置</button></div>
</div><div id="toast"></div>
<script>
const $=id=>document.getElementById(id);
let cfg={};
function toast(msg,err){const t=$('toast');t.textContent=msg;
t.className=err?'show err':'show';
clearTimeout(t._h);t._h=setTimeout(()=>t.className='',2200)}
/* ---- 快捷键录制器 ---- */
const MODS={Control:'ctrl',Alt:'alt',Shift:'shift',Meta:'win'};
const NAMES={Enter:'enter',Tab:'tab',Space:'space',Backspace:'backspace',
Escape:'escape',ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right'};
function keyName(e){
let k=e.key;
if(/^Key[A-Z]$/.test(e.code))k=e.code.slice(3).toLowerCase();
else if(/^Digit[0-9]$/.test(e.code))k=e.code.slice(5);
else if(/^F\d{1,2}$/.test(e.code))k=e.code.toLowerCase();
else if(NAMES[k])k=NAMES[k];
else k=k.toLowerCase();
return k}
function makeRecorder(el){
let mods=[],done=true,restore='';
el.addEventListener('click',()=>{if(!done)return;mods=[];done=false;
restore=el.value;el.classList.add('rec');el.value='按下组合键…'});
function finish(){if(done)return;done=true;
el.classList.remove('rec');
if(el.value==='按下组合键…')el.value=restore}
el.addEventListener('keydown',e=>{if(done)return;e.preventDefault();
e.stopPropagation();
if(MODS[e.key]){if(!mods.includes(MODS[e.key]))mods.push(MODS[e.key]);
el.value=mods.join('+');
if(mods.length>=2){finish()}   // 纯修饰键和弦(如 ctrl+win):两个即定格
return}
const k=keyName(e);
if(!k||k==='escape'){finish();if(k==='escape')el.value=restore;return}
el.value=[...mods,k].join('+');finish()});
el.addEventListener('keyup',e=>{if(done)return;
const m=MODS[e.key];
if(m){mods=mods.filter(x=>x!==m);
el.value=mods.join('+')||'按下组合键…'}});
el.addEventListener('blur',()=>{if(done)return;
/* Alt+Tab 等系统级组合会把窗口切走:浏览器收不到触发键也收不到修饰键
抬起,凭"Alt/Shift 仍处于按住 + 失焦"推断为 修饰键+Tab 完成录入 */
if(mods.length&&mods.every(m=>m==='alt'||m==='shift'))
el.value=[...mods,'tab'].join('+');
finish()})}
['hotkey_key','act_enter','act_alt_tab'].forEach(id=>makeRecorder($(id)));
/* ---- 恢复默认键位 ---- */
const DEFAULTS={hotkey_key:'ctrl+win',act_enter:'enter',act_alt_tab:'alt+tab'};
[['hotkey_key','def_hotkey'],['act_enter','def_enter'],
['act_alt_tab','def_alt_tab']].forEach(([id,b])=>{
$(b).addEventListener('click',()=>{$(id).value=DEFAULTS[id];
toast('已恢复默认键位,保存后生效')})});
/* ---- 触发方式单选 ---- */
function setMode(m){cfg.hotkey_mode=m;
[...$('hotkey_mode').children].forEach(b=>
b.classList.toggle('on',b.dataset.v===m))}
$('hotkey_mode').addEventListener('click',e=>{
if(e.target.dataset.v)setMode(e.target.dataset.v)});
/* ---- 装载 ---- */
async function boot(){
cfg=await(await fetch('/api/config')).json();
$('hotkey_key').value=cfg.hotkey_key;
$('act_enter').value=cfg.key_actions.enter;
$('act_alt_tab').value=cfg.key_actions.alt_tab;
$('hysteresis_ms').value=cfg.alt_tab_hysteresis_ms;
setMode(cfg.hotkey_mode);
$('device_ip').value=cfg.device_ip;$('udp_port').value=cfg.udp_port;
try{const d=await(await fetch('/api/devices')).json();
const sel=$('output_substr');sel.innerHTML='';
const cur=cfg.output_substr;
let has=false;
d.outputs.forEach(n=>{const o=document.createElement('option');
o.value=o.textContent=n;if(n===cur)has=true;sel.appendChild(o)});
if(!has&&cur){const o=document.createElement('option');
o.value=o.textContent=cur+'(未检测到)';sel.appendChild(o)}
const warn=$('cable-warn');
if(warn)warn.style.display=d.cable_found?'none':'block'}catch(e){}
try{const s=await(await fetch('/api/status')).json();
$('autostart').checked=s.autostart;paint(s.forwarder_running)}catch(e){}}
function paint(run){$('st-dot').classList.toggle('on',run);
$('fw-state').textContent=run?'转发器运行中':'转发器未运行'}
/* ---- 保存 ---- */
$('save').addEventListener('click',async()=>{
const body={hotkey_key:$('hotkey_key').value,
hotkey_mode:cfg.hotkey_mode,
key_actions:{enter:$('act_enter').value,alt_tab:$('act_alt_tab').value},
alt_tab_hysteresis_ms:$('hysteresis_ms').value,
device_ip:$('device_ip').value.trim(),
udp_port:$('udp_port').value,
output_substr:$('output_substr').value};
const r=await(await fetch('/api/config',{method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify(body)})).json();
if(r.ok){toast('已保存,已即时生效')}
else toast('保存失败: '+r.errors.join(';'),true)});
/* ---- 自启 / 重启 / 日志轮询 ---- */
$('autostart').addEventListener('change',async e=>{
await fetch('/api/autostart',{method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({on:e.target.checked})});
toast(e.target.checked?'已开启开机自启':'已关闭开机自启')});
$('restart').addEventListener('click',async()=>{
const r=await(await fetch('/api/restart',{method:'POST'})).json();
toast(r.ok?'转发器已重启':'重启失败,请看日志',!r.ok)});
setInterval(async()=>{try{
const s=await(await fetch('/api/status')).json();
paint(s.forwarder_running);
$('log').textContent=s.log||'(暂无日志)'}catch(e){}},2000);
boot();
</script></body></html>
"""


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------

class SettingsHandler(BaseHTTPRequestHandler):
    # 由 make_server 注入:forwarder 状态/重启回调由托盘提供
    app = None   # dict: get_status -> dict, restart -> bool, config_path -> str

    def log_message(self, fmt, *args):   # 静默访问日志
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _page(self):
        data = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        app = self.app or {}
        path = self.path.split("?")[0]
        if path == "/" or path == "/index.html":
            self._page()
        elif path == "/api/config":
            self._json(load_config(app["config_path"]()))
        elif path == "/api/devices":
            names, cable = list_output_devices()
            self._json({"outputs": names, "cable_found": cable})
        elif path == "/api/status":
            st = app.get("get_status", lambda: {})()
            self._json({"forwarder_running": bool(st.get("running")),
                        "autostart": is_autostart_on(),
                        "log": st.get("log", "")})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        app = self.app or {}
        path = self.path.split("?")[0]
        if path == "/api/config":
            body = self._body()
            old = load_config(app["config_path"]())
            clean, errors = validate_config(body, old)
            if errors:
                self._json({"ok": False, "errors": errors}, 400)
                return
            try:
                save_config(app["config_path"](), clean)
            except OSError as e:
                self._json({"ok": False, "errors": [f"写入配置失败: {e}"]}, 500)
                return
            self._json({"ok": True, "config": clean})
        elif path == "/api/autostart":
            body = self._body()
            try:
                set_autostart(bool(body.get("on")))
                self._json({"ok": True})
            except OSError as e:
                self._json({"ok": False, "errors": [str(e)]}, 500)
        elif path == "/api/restart":
            ok = bool(app.get("restart", lambda: False)())
            self._json({"ok": ok}, 200 if ok else 500)
        else:
            self._json({"error": "not found"}, 404)


def make_server(config_path, get_status=None, restart=None, port=DEFAULT_PORT):
    """创建设置页 HTTP 服务(未 start;调用方负责 serve_forever)。"""
    SettingsHandler.app = {
        "config_path": config_path,
        "get_status": get_status or (lambda: {"running": False, "log": ""}),
        "restart": restart or (lambda: False),
    }
    return ThreadingHTTPServer(("127.0.0.1", port), SettingsHandler)


def main():
    port = DEFAULT_PORT
    server = make_server(lambda: os.path.join(BASE_DIR, "voice-config.json"),
                         port=port)
    print(f"设置面板: http://127.0.0.1:{port} (Ctrl+C 退出)")
    webbrowser.open(f"http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
