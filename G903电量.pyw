"""
G903 LIGHTSPEED 电量 GUI v1（双击自动读数 + 定时自动刷新）

- 复用 g903_battery.py 的 HID++ 读取逻辑（feature 0x1001 Battery Voltage）。
- tkinter GUI：通道/电压/充电状态/估算电量/趋势结论 + 历史记录。
- 启动即读一次，可按设定间隔（默认 60s）持续自动刷新。
- 读数在线程中执行，界面不卡顿；数据仍写入 g903_battery_history.csv。

依赖：pip install hid
"""

import csv
import io
import os
import sys
import threading
import time
from datetime import datetime

import hid
import tkinter as tk
from tkinter import ttk, messagebox

APP_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_CSV = os.path.join(APP_DIR, "g903_battery_history.csv")

VID = 0x046D
PID_PRIORITY = {0xC086: 0, 0xC539: 1}

REPORT_ID_LONG = 0x11
DEVICE_IDX = 0x01
FEATURE_BATTERY_VOLTAGE = 0x1001
SW_ID = 0x0A

REPORT_LEN = 20
FRAME_ERROR = 0x8F

SAMPLES = 3
MIN_REAL_DELTA = 15

DISCHARGE_CURVE = [
    (4200, 100), (4100, 94), (4000, 88), (3950, 82), (3900, 76),
    (3850, 68), (3800, 60), (3770, 52), (3750, 47), (3720, 42),
    (3690, 36), (3660, 30), (3600, 22), (3500, 12), (3400, 5),
    (3300, 0),
]


# ---------- 以下读取逻辑复用自 g903_battery.py ----------

def build_request(device_idx, feature_idx, function_id, params):
    if len(params) > 16:
        raise ValueError(f"params 长度超过 16 字节: {len(params)}")
    func_sw = ((function_id & 0x0F) << 4) | (SW_ID & 0x0F)
    payload = list(params) + [0x00] * (16 - len(params))
    return [REPORT_ID_LONG, device_idx, feature_idx, func_sw] + payload


def send_and_wait(dev, report, timeout_ms=800):
    dev.write(report)
    resp = dev.read(REPORT_LEN, timeout_ms=timeout_ms)
    if resp and len(resp) >= 1 and resp[0] == REPORT_ID_LONG and resp[1] == report[1]:
        return resp
    return None


def check_error(resp):
    if len(resp) > 2 and resp[2] == FRAME_ERROR:
        err_code = resp[5] if len(resp) > 5 else resp[-1]
        raise RuntimeError(f"设备返回错误，错误码 0x{err_code:02x}")


def get_feature_index(dev, feature_id):
    fid_hi = (feature_id >> 8) & 0xFF
    fid_lo = feature_id & 0xFF
    resp = send_and_wait(dev, build_request(DEVICE_IDX, 0x00, 0x00, [fid_hi, fid_lo, 0x00]))
    if not resp:
        raise RuntimeError(f"查询 feature 0x{feature_id:04x} 无响应")
    check_error(resp)
    if len(resp) <= 4:
        raise RuntimeError(f"查询 feature 0x{feature_id:04x} 响应过短")
    feature_idx = resp[4]
    if feature_idx == 0:
        raise RuntimeError(f"设备不支持 feature 0x{feature_id:04x}")
    return feature_idx


def parse_battery_response(resp):
    if len(resp) <= 6:
        raise RuntimeError("电量响应过短，无法解析电压与充电状态")
    voltage_mv = int.from_bytes(bytes(resp[4:6]), "big")
    status_byte = resp[6]
    return voltage_mv, bool(status_byte & 0x80)


def get_battery(dev, battery_feature_idx):
    resp = send_and_wait(dev, build_request(DEVICE_IDX, battery_feature_idx, 0x00, [0x00, 0x00, 0x00]))
    if not resp:
        raise RuntimeError("查询电量无响应")
    check_error(resp)
    return resp


def estimate_percent(voltage_mv):
    if voltage_mv >= DISCHARGE_CURVE[0][0]:
        return DISCHARGE_CURVE[0][1]
    if voltage_mv <= DISCHARGE_CURVE[-1][0]:
        return DISCHARGE_CURVE[-1][1]
    for (v_hi, p_hi), (v_lo, p_lo) in zip(DISCHARGE_CURVE, DISCHARGE_CURVE[1:]):
        if v_lo <= voltage_mv <= v_hi:
            frac = (voltage_mv - v_hi) / (v_lo - v_hi)
            return round(p_hi + frac * (p_lo - p_hi))
    return None


def find_hidpp_long_paths():
    candidates = []
    for info in hid.enumerate(VID):
        if info.get("usage_page") == 0xFF00 and info.get("usage") == 0x0002:
            pid = info.get("product_id")
            candidates.append((PID_PRIORITY.get(pid, 2), info["path"], pid))
    candidates.sort(key=lambda x: x[0])
    return [(path, pid) for _, path, pid in candidates]


def probe_feature(path, feature_id):
    dev = None
    try:
        dev = hid.device()
        dev.open_path(path)
        fid_hi = (feature_id >> 8) & 0xFF
        fid_lo = feature_id & 0xFF
        resp = send_and_wait(dev, build_request(DEVICE_IDX, 0x00, 0x00, [fid_hi, fid_lo, 0x00]))
        return bool(resp and len(resp) > 4 and resp[4] != 0)
    except Exception:
        return False
    finally:
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass


def find_active_hidpp_path():
    for path, pid in find_hidpp_long_paths():
        if probe_feature(path, FEATURE_BATTERY_VOLTAGE):
            return path, pid
    return None, None


def measure(dev, batt_idx, samples=SAMPLES):
    values = []
    charging = False
    last_resp = None
    for _ in range(samples):
        resp = get_battery(dev, batt_idx)
        v, charging = parse_battery_response(resp)
        values.append(v)
        last_resp = resp
    values.sort()
    return values, values[samples // 2], charging, last_resp


def append_history(v1, v2, v3, median, charging, percent):
    new_file = not os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["time", "v1", "v2", "v3", "voltage", "charging", "percent"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"),
                    v1, v2, v3, median, int(charging), percent])


def summarize_history():
    if not os.path.exists(HISTORY_CSV):
        return None
    rows = []
    charging_excluded = 0
    with open(HISTORY_CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                t = datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S")
                v = int(r["voltage"])
                charging = int(r.get("charging", 0))
                if charging:
                    charging_excluded += 1
                    continue
                rows.append((t, v))
            except (KeyError, ValueError):
                continue
    n = len(rows)
    if n < 2:
        return f"静置记录仅 {n} 条（另 {charging_excluded} 条充电读数已排除），暂无法判断耗电趋势。"

    vols = [v for _, v in rows]
    lo, hi = min(vols), max(vols)
    span_h = (rows[-1][0] - rows[0][0]).total_seconds() / 3600

    if n < 4:
        return (f"静置 {n} 条 / 跨度 {span_h:.1f} 小时，电压 {lo}~{hi} mV"
                f"（波动 ±{(hi - lo) // 2} mV，已排除 {charging_excluded} 条充电读数），样本还太少。")

    k = 3
    first_avg = sum(v for _, v in rows[:k]) / k
    last_avg = sum(v for _, v in rows[-k:]) / k
    delta = round(last_avg - first_avg)

    if delta <= -MIN_REAL_DELTA:
        return f"结论：静置电压较初期下降约 {-delta} mV，可观察到真实耗电（静置 {n} 条 / 跨度 {span_h / 24:.1f} 天，已排除 {charging_excluded} 条充电读数）。"
    if delta >= MIN_REAL_DELTA:
        return f"结论：静置读数较初期升高 {delta} mV，但仍在噪声范围内（静置极差 {hi - lo} mV），不代表充电。"
    return f"结论：静置电压整体平稳（前后差 {abs(delta)} mV，噪声极差 {hi - lo} mV），暂未观察到明显耗电变化（静置 {n} 条 / 跨度 {span_h / 24:.1f} 天，已排除 {charging_excluded} 条充电读数）。"


# ---------- 读数（在线程中执行） ----------

def read_once():
    """执行一次完整读数，返回 (info_dict, summary, error)。"""
    path, pid = find_active_hidpp_path()
    if not path:
        return None, None, "未找到可用的长报文 HID++ 接口"

    dev = None
    try:
        dev = hid.device()
        dev.open_path(path)
        channel = "有线" if pid == 0xC086 else ("无线" if pid == 0xC539 else f"PID 0x{pid:04x}")

        batt_idx = get_feature_index(dev, FEATURE_BATTERY_VOLTAGE)
        values, median, charging, last_resp = measure(dev, batt_idx)
        percent = estimate_percent(median)

        append_history(values[0], values[1], values[2], median, charging, percent)
        summary = summarize_history()

        info = {
            "channel": channel,
            "pid": pid,
            "values": values,
            "voltage": median,
            "charging": charging,
            "percent": percent,
            "raw": [hex(b) for b in last_resp],
        }
        return info, summary, None
    except (RuntimeError, OSError, ValueError) as e:
        return None, None, f"出错: {e}"
    except Exception as e:
        return None, None, f"未知错误: {e}"
    finally:
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass


# ---------- GUI ----------

# 配色 token：深石墨底 + 一块亮蓝绿的“电量核心”高亮。
# 除核心读数外全部低对比、单字重，不做多余装饰。
C = {
    "bg":       "#14171B",   # 窗口底色（近黑，但带一点蓝而非纯黑）
    "panel":    "#1E2329",   # 卡片底
    "panel_hi": "#262D35",   # 核心读数卡片底
    "text":     "#E8ECEF",   # 主要文字
    "muted":    "#8A939C",   # 次要文字 / 标签
    "accent":   "#5EE0C9",   # 电量核心强调色（蓝绿，非默认 acid-green）
    "border":   "#2A323A",
    "ok":       "#5EE0C9",
    "warn":     "#F0B35C",
}

class BatteryApp:
    def __init__(self, root):
        self.root = root
        self.running = False
        self.after_id = None
        self.read_seq = 0

        root.title("G903 电量")
        root.geometry("560x560")
        root.minsize(520, 500)
        root.configure(bg=C["bg"])

        # 整套控件统一配色
        style = ttk.Style(root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", background=C["bg"], foreground=C["text"],
                        fieldbackground=C["panel"], bordercolor=C["border"],
                        lightcolor=C["border"], darkcolor=C["border"],
                        troughcolor=C["panel"], focuscolor=C["accent"])
        style.configure("TLabel", background=C["bg"], foreground=C["text"])
        style.configure("Muted.TLabel", background=C["bg"], foreground=C["muted"])
        style.configure("Panel.TFrame", background=C["panel"])
        style.configure("Hi.TFrame", background=C["panel_hi"])
        style.configure("TButton", background=C["panel_hi"], foreground=C["text"],
                        bordercolor=C["border"], focuscolor=C["accent"],
                        padding=(14, 7))
        style.map("TButton",
                  background=[("active", "#333B44"), ("disabled", C["panel"])],
                  foreground=[("disabled", C["muted"])])
        style.configure("Accent.TButton", background=C["accent"], foreground="#0C1513",
                        bordercolor=C["accent"], font=("Segoe UI", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#6EF0DA")])
        style.configure("TSpinbox", background=C["panel"], foreground=C["text"],
                        fieldbackground=C["panel"], arrowsize=13, padding=4)

        outer = ttk.Frame(root, padding=20, style="TFrame")
        outer.pack(fill="both", expand=True)

        # 顶部：产品名 + 通道（一行，低调）
        head = ttk.Frame(outer, style="TFrame")
        head.pack(fill="x")
        ttk.Label(head, text="Logitech G903", font=("Segoe UI", 13, "bold")).pack(side="left")
        self.channel_var = tk.StringVar(value="连接中…")
        ttk.Label(head, textvariable=self.channel_var, style="Muted.TLabel",
                  font=("Segoe UI", 10)).pack(side="right")

        # 核心读数（hero）：唯一的大号亮点
        # 底部 Canvas 高于可见卡片：上方是读数区，底部外沿向下有滴落区。
        self.hero_card_h = 150   # 可见卡片高度
        self.hero_drop_h = 42    # 卡片底边下方“掉泡泡”区
        self.hero = tk.Canvas(outer, height=self.hero_card_h + self.hero_drop_h,
                              bg=C["bg"], highlightthickness=0, bd=0)
        self.hero.pack(fill="x", pady=(14, 12))
        self.hero.bind("<Configure>", lambda e: self._redraw_hero_card())

        self.voltage_var = tk.StringVar(value="· · ·")
        self.voltage_lbl = tk.Label(self.hero, textvariable=self.voltage_var,
                 font=("Segoe UI", 42, "bold"), foreground=C["accent"],
                 bg=C["panel_hi"])
        self.voltage_lbl.place(x=22, y=10)

        hero_sub = tk.Frame(self.hero, bg=C["panel_hi"])
        hero_sub.place(x=24, y=112)
        tk.Label(hero_sub, text="电量约 ", font=("Segoe UI", 10),
                 fg=C["muted"], bg=C["panel_hi"]).pack(side="left", anchor="s")
        self.percent_var = tk.StringVar(value="—")
        tk.Label(hero_sub, textvariable=self.percent_var, font=("Segoe UI", 16, "bold"),
                 fg=C["text"], bg=C["panel_hi"]).pack(side="left", anchor="s")

        # 泡泡动画状态
        self.charging = False
        self._bubbles = None
        self._charging_now = None
        self._card_rect = None

        # 次要信息卡（充电状态 / 采样 / 最后读取）
        panel = ttk.Frame(outer, style="Panel.TFrame")
        panel.pack(fill="x", ipady=12)

        self.charging_var = tk.StringVar(value="—")
        self.charging_lbl = tk.Label(panel, textvariable=self.charging_var,
                                     font=("Segoe UI", 11, "bold"),
                                     bg=C["panel"], fg=C["muted"], anchor="w")
        self.charging_lbl.pack(side="left", padx=16)

        self.time_var = tk.StringVar(value="—")
        right_box = tk.Frame(panel, bg=C["panel"])
        right_box.pack(side="right", padx=16)
        ttk.Label(right_box, text="采样 ", style="Muted.TLabel",
                  background=C["panel"]).pack(side="left")
        self.samples_var = tk.StringVar(value="—")
        tk.Label(right_box, textvariable=self.samples_var, font=("Segoe UI", 10),
                 bg=C["panel"], fg=C["text"]).pack(side="left")

        # 趋势结论（安静的正文段落，不用框线）
        self.trend_var = tk.StringVar(value="连接接收器并读取一次后，这里会显示耗电趋势。")
        tk.Label(outer, textvariable=self.trend_var, wraplength=500, justify="left",
                 font=("Segoe UI", 10), bg=C["bg"], fg=C["muted"]).pack(
                     anchor="w", pady=(16, 0))

        # 控制区
        ctrl = ttk.Frame(outer, style="TFrame")
        ctrl.pack(fill="x", pady=(18, 0))

        self.read_btn = ttk.Button(ctrl, text="读取电量", style="Accent.TButton",
                                   command=self.read_now)
        self.read_btn.pack(side="left")

        self.start_btn = ttk.Button(ctrl, text="自动刷新", command=self.toggle_auto)
        self.start_btn.pack(side="left", padx=8)

        ttk.Label(ctrl, text="每", style="Muted.TLabel").pack(side="left")
        self.interval_var = tk.StringVar(value="60")
        self.interval_spin = ttk.Spinbox(ctrl, from_=5, to=3600, textvariable=self.interval_var,
                                         width=5, validate="key")
        self.interval_spin.pack(side="left", padx=(4, 2))
        ttk.Label(ctrl, text="秒", style="Muted.TLabel").pack(side="left")

        self.dev_btn = ttk.Button(ctrl, text="开发者日志", command=self.open_devlog)
        self.dev_btn.pack(side="right")

        # 状态条（错误=琥珀色，正常=灰色）
        self.note_var = tk.StringVar(value="等待读取…")
        self.note_lbl = tk.Label(outer, textvariable=self.note_var, anchor="w",
                                 font=("Segoe UI", 9), bg=C["bg"], fg=C["muted"])
        self.note_lbl.pack(fill="x", pady=(14, 0))

        # 开发者级数据缓存（不在主界面展示，进日志弹窗查看）
        self._last_info = None

        # 启动即读一次 + 泡泡动画循环
        self._charging_now = None
        self.root.after(100, self.read_now)
        self._animate()

    def _set(self, var, value):
        var.set(value)

    def _set_note(self, text, warn=False):
        self._set(self.note_var, text)
        self.note_lbl.config(fg=C["warn"] if warn else C["muted"])

    # ---------- 泡泡动画 ----------
    def _mix(self, hex1, hex2, t):
        """把 hex1 按比例 t 混入 hex2（t=0 纯 hex2，t=1 纯 hex1）。"""
        r1, g1, b1 = int(hex1[1:3], 16), int(hex1[3:5], 16), int(hex1[5:7], 16)
        r2, g2, b2 = int(hex2[1:3], 16), int(hex2[3:5], 16), int(hex2[5:7], 16)
        r = round(r2 + (r1 - r2) * t)
        g = round(g2 + (g1 - g2) * t)
        b = round(b2 + (b1 - b2) * t)
        return "#%02X%02X%02X" % (r, g, b)

    def _redraw_hero_card(self):
        """重绘“卡片”矩形（只盖住读数区，底部留滴落区），并把卡片抬到泡泡之上。"""
        w = self.hero.winfo_width()
        self.hero.delete("card")
        self.hero.create_rectangle(0, 0, w, self.hero_card_h,
                                   fill=C["panel_hi"], outline="", tags="card")
        # 层序：泡泡在下 → 卡片在上（泡泡“生于卡片后方”，从底边露出后才可见）
        self.hero.tag_raise("card")

    def _bubble_color(self, progress, charging):
        """progress: 0=贴边 1=最远。越靠外越淡；充电反向时越靠边越浓。"""
        # 落下过程中由 accent 渐变回底色（bg），越往下越淡
        return self._mix(C["accent"], C["bg"], 1.0 - progress if not charging else progress)

    def _spawn_bubbles(self, charging):
        import random
        w = self.hero.winfo_width()
        if w < 20:
            w = 540
        bottom = self.hero_card_h - 12     # 出生线在卡片内部，泡泡完全藏于卡片后方
        n = 18
        self._bubbles = []
        for i in range(n):
            # 中间密度高、向两侧递减：用两个均匀数相加（近似三角分布，峰值在中心）
            x = w * 0.06 + (w * 0.88) * ((random.random() + random.random()) / 2.0)
            # 半径上限随到中心的距离向两侧收缩：中心最大 7.0，最边最小 2.0，杜绝两侧出大泡泡
            edge = abs(x - w / 2.0) / (w / 2.0)      # 0=正中, 1=最边缘
            r_max = 7.0 - 5.0 * edge
            self._bubbles.append({
                "x": x,
                "y": bottom,
                "base_r": random.uniform(2.0, r_max),
                "delay": random.uniform(0, 1.2),
                "dur": random.uniform(1.1, 2.2),
                "drop": random.uniform(20, self.hero_drop_h + 10),
                "drift": random.uniform(-6, 6),
            })

    def _draw_bubbles(self, frame_t, charging):
        if self._bubbles is None:
            self._spawn_bubbles(charging)
        self.hero.delete("bubble")
        for b in self._bubbles:
            local = (frame_t - b["delay"]) % b["dur"] / b["dur"]
            # 未充电：0→1 向下掉落、越落越小越淡；充电：1→0 从下向上回收、越收越大越浓
            progress = local if not charging else 1.0 - local
            y = b["y"] + b["drop"] * progress
            x = b["x"] + b["drift"] * progress
            # progress 越大半径越小（贴边时最大，落到底最小）
            r = b["base_r"] * (1.7 - 1.3 * progress)
            color = self._bubble_color(progress, charging)
            self.hero.create_oval(x - r, y - r, x + r, y + r,
                                  fill=color, outline=color, tags="bubble")
        # 每帧新建的泡泡默认在顶层，重新把卡片抬到泡泡之上，保持“生在卡片后方”
        self.hero.tag_raise("card")

    def _animate(self):
        if not self.hero.winfo_exists():
            return
        self._anim_t = getattr(self, "_anim_t", 0.0) + 1 / 30.0
        if self._charging_now is None:
            self._draw_bubbles(self._anim_t * 0.5, False)
        else:
            self._draw_bubbles(self._anim_t, self._charging_now)
        self.root.after(33, self._animate)

    def read_now(self):
        if self.running:
            return
        self.running = True
        self.read_btn.config(state="disabled")
        self._set_note("读取中…")

        self.read_seq += 1
        seq = self.read_seq

        def worker():
            info, summary, err = read_once()
            if seq != self.read_seq:
                return

            def done():
                self.running = False
                self.read_btn.config(state="normal")
                if err:
                    self._show_error(err)
                    return
                self.apply(info, summary)
            try:
                self.root.after(0, done)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _show_error(self, err):
        if "接口" in err or "无响应" in err or "不支持" in err:
            msg = "没找到 G903 的接收器。请确认鼠标已开启，或插上 Unifying / Lightspeed 接收器后重试。"
        else:
            msg = "读取失败，请重试。"
        self._set_note(f"{msg}（{err}）", warn=True)

    def open_devlog(self):
        """弹窗展示开发者级数据：原始字节、PID、feature、CSV 路径、历史记录尾部。"""
        win = tk.Toplevel(self.root)
        win.title("开发者日志")
        win.geometry("520x460")
        win.minsize(460, 360)
        win.configure(bg=C["bg"])

        box = tk.Frame(win, bg=C["bg"])
        box.pack(fill="both", expand=True, padx=16, pady=14)

        info = self._last_info
        lines = []
        lines.append(f"Logitech G903 · 开发者日志")
        lines.append(f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        if info:
            lines.append(f"通道：{info['channel']}")
            lines.append(f"PID：0x{info['pid']:04X}")
            lines.append(f"原始响应字节：{' '.join(info['raw'])}")
            lines.append(f"本次采样：{info['values']}")
            lines.append(f"充电标志位：{int(info['charging'])}")
        else:
            lines.append("尚无读数。请先点击「读取电量」。")
        lines.append("")
        lines.append("常量：VID=0x046D  REPORT_ID=0x11  FEATURE=0x1001(Battery Voltage)")
        lines.append(f"历史 CSV：{HISTORY_CSV}")

        txt = tk.Text(box, bg=C["bg"], fg=C["text"], font=("Consolas", 10),
                      insertbackground=C["accent"], relief="flat", wrap="word",
                      highlightthickness=0, padx=4, pady=4)
        txt.pack(fill="both", expand=True)

        # 追加最近若干条历史读数
        tail = []
        try:
            if os.path.exists(HISTORY_CSV):
                with open(HISTORY_CSV, encoding="utf-8") as f:
                    tail = f.read().strip().splitlines()[-15:]
        except Exception:
            tail = []
        lines.append("")
        lines.append("— 历史记录（最近 15 行）—")
        lines.extend(tail if tail else ["（无记录）"])

        txt.insert("1.0", "\n".join(lines))
        txt.config(state="disabled")

        close = ttk.Button(box, text="关闭", command=win.destroy)
        close.pack(pady=(10, 0))

    def apply(self, info, summary):
        import random
        self._set(self.channel_var, f"{info['channel']} 连接")
        self._set(self.voltage_var, f"{info['voltage']} mV")
        self.charging = bool(info["charging"])
        if self.charging:
            self._set(self.charging_var, "● 充电中")
            self.charging_lbl.config(fg=C["warn"])
        else:
            self._set(self.charging_var, "● 未充电")
            self.charging_lbl.config(fg=C["accent"])
        # 泡泡方向随充电状态切换：未充电向下掉落，充电反向回收
        if self._charging_now != self.charging:
            self._charging_now = self.charging
            self._spawn_bubbles(self.charging)
            self._anim_t = random.uniform(0, 1)
        self._set(self.percent_var, f"{info['percent']}%")
        v1, v2, v3 = info["values"]
        self._set(self.samples_var, f"3 次 [{v1} {v2} {v3}]")
        self._last_info = dict(info)
        if summary:
            self._set(self.trend_var, summary)
        if self.after_id is not None:
            self._set_note(f"自动刷新中 · 每 {self.interval_var.get()} 秒")
        else:
            self._set_note("已更新")

    def toggle_auto(self):
        if self.after_id is not None:
            self._stop_auto()
        else:
            self._start_auto()

    def _start_auto(self):
        try:
            interval = float(self.interval_var.get())
        except ValueError:
            interval = 60
            self._set(self.interval_var, "60")
        interval = max(5.0, min(3600.0, interval))
        self._set(self.interval_var, str(int(interval)))
        self.start_btn.config(text="停止刷新")
        self._set_note(f"自动刷新中 · 每 {int(interval)} 秒")
        self.read_now()
        self._schedule(interval * 1000)

    def _schedule(self, ms):
        if self.after_id is not None:
            return
        self.after_id = self.root.after(int(ms), self._tick)

    def _tick(self):
        self.after_id = None
        self.read_now()
        try:
            interval = float(self.interval_var.get())
        except ValueError:
            interval = 60
        interval = max(5.0, min(3600.0, interval))
        self.after_id = self.root.after(int(interval * 1000), self._tick)

    def _stop_auto(self):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.start_btn.config(text="自动刷新")
        self._set_note("自动刷新已关闭")


def main():
    root = tk.Tk()
    BatteryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()