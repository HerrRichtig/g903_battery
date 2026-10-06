"""
G903 LIGHTSPEED 控制面板 GUI v2
================================

在 v1（电量查询）基础上新增：
  - 读取并设置 DPI（feature 0x2201 AdjustableDpi）
  - 读取并设置轮询率（feature 0x8060 ReportRate，单位毫秒间隔）

HID++ 底层逻辑从 g903_control 复用，电量逻辑从 g903_battery 复用。
"""
import threading
import time

import tkinter as tk
from tkinter import ttk, messagebox

from . import g903_control as ctl
import g903_battery as bat
from . import g903_battery_wave as wave
from .theme import C, apply_base_style

AUTO_REFRESH_MS = 10000   # 固定 10 秒后台刷新

def _read_control():
    """读 DPI 与轮询率，返回 (dict, err)。"""
    try:
        with ctl.open_device_cm() as (dev, pid):
            if dev is None:
                return None, "未找到 G903 长报文 HID++ 接口"
            dpi_idx = ctl.get_index(dev, ctl.FEATURE_ADJUSTABLE_DPI)
            rr_idx = ctl.get_index(dev, ctl.FEATURE_REPORT_RATE)
            return ctl.snapshot(dev, dpi_idx, rr_idx), None
    except Exception as e:
        return None, f"出错: {e}"

def _apply_dpi(dpi):
    try:
        with ctl.open_device_cm() as (dev, pid):
            if dev is None:
                return "未找到 G903 长报文 HID++ 接口"
            dpi_idx = ctl.get_index(dev, ctl.FEATURE_ADJUSTABLE_DPI)
            ctl.set_dpi(dev, dpi_idx, dpi)
            return None
    except Exception as e:
        return f"设置 DPI 失败: {e}"

def _apply_rate(rate_ms):
    try:
        with ctl.open_device_cm() as (dev, pid):
            if dev is None:
                return "未找到 G903 长报文 HID++ 接口"
            rr_idx = ctl.get_index(dev, ctl.FEATURE_REPORT_RATE)
            ctl.set_report_rate_with_host_mode(dev, rr_idx, rate_ms)
            return None
    except Exception as e:
        return f"设置轮询率失败: {e}"

class BatteryApp:
    palette = C

    def __init__(self, root):
        C = self.palette
        self.root = root
        self.running = False
        self.after_id = None
        self._last_info = None
        self._last_ctrl = None
        root.title("G903 控制面板")
        root.geometry("680x760")
        root.minsize(560, 740)
        root.configure(bg=C["bg"])
        style = ttk.Style(root)
        self._apply_style(style)
        outer = ttk.Frame(root, padding=(28, 20))
        outer.pack(fill="both", expand=True)
        self._build_header(outer)
        self._build_footer(outer)

        nb = ttk.Notebook(outer)
        nb.pack(fill="both", expand=True, pady=(0, 4))
        tab_batt = ttk.Frame(nb, padding=(0, 14))
        tab_perf = ttk.Frame(nb, padding=(0, 14))
        tab_dev = ttk.Frame(nb, padding=(0, 14))
        nb.add(tab_batt, text="01  电量")
        nb.add(tab_perf, text="02  性能设置")
        nb.add(tab_dev, text="03  开发者日志")

        self._build_battery_section(tab_batt)
        self._build_control_section(tab_perf)
        self._build_devlog_section(tab_dev)
        outer.bind("<Configure>", self._resize_text)
        root.bind("<F5>", lambda event: self.read_now())
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(100, self.read_now)
        self.after_id = self.root.after(AUTO_REFRESH_MS, self._tick)

    def _apply_style(self, style):
        apply_base_style(style)

    def _build_header(self, outer):
        C = self.palette
        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="LOGITECH / LIGHTSPEED", font=("Arial", 10, "bold")).pack(side="left")
        ttk.Label(head, text="控制面板 / 01", foreground=C["accent"]).pack(side="right")
        title = ttk.Frame(outer)
        title.pack(fill="x", pady=(8, 12))
        ttk.Label(title, text="G903", font=("Arial", 52, "bold")).pack(anchor="w")
        status = ttk.Frame(title)
        status.pack(fill="x", pady=(4, 0))
        self.channel_var = tk.StringVar(value="正在连接鼠标…")
        ttk.Label(status, textvariable=self.channel_var, foreground=C["muted"]).pack(side="left")
        ttk.Label(status, text="HID++ / 10 秒自动刷新", foreground=C["muted"]).pack(side="right")
        tk.Frame(outer, bg=C["text"], height=3).pack(fill="x", pady=(0, 12))

    def _build_battery_section(self, outer):
        C = self.palette
        hero = tk.Frame(outer, bg=C["bg"])
        hero.pack(fill="both", expand=True, pady=(0, 20))
        hero.columnconfigure(0, weight=1)
        hero.rowconfigure(0, weight=1)
        reading = tk.Frame(hero, bg=C["bg"])
        reading.grid(row=0, column=0, sticky="w", padx=(0, 20))
        self.wave_bar = wave.BatteryWaveBar(
            hero, width=96, height=224, track="#E5E5E3", border="#B8B8B5",
            fill="#D99A28", low_fill="#B77918", low_threshold=20,
            bg=C["bg"])
        self.wave_bar.grid(row=0, column=1, sticky="e")
        tk.Label(reading, text="电池 / 估算电量", bg=C["bg"], fg=C["text"],
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w")
        self.percent_var = tk.StringVar(value="—")
        tk.Label(reading, textvariable=self.percent_var, bg=C["bg"], fg=C["text"],
                 font=("Arial", 72, "bold")).pack(anchor="w", pady=(8, 4))
        self.charging_var = tk.StringVar(value="等待读取")
        self.charging_lbl = tk.Label(reading, textvariable=self.charging_var,
                                     bg=C["bg"], fg=C["muted"],
                                     font=("Microsoft YaHei UI", 10))
        self.charging_lbl.pack(anchor="w")
        ttk.Separator(outer).pack(fill="x", pady=(0, 12))
        details = ttk.Frame(outer)
        details.pack(fill="x")
        self.voltage_var = tk.StringVar(value="电压 —")
        self.time_var = tk.StringVar(value="尚未更新")
        ttk.Label(details, textvariable=self.voltage_var).pack(side="left")
        ttk.Label(details, textvariable=self.time_var, foreground=C["muted"]).pack(side="right")
        self.battery_hint = ttk.Label(
            outer, text="电量由电压估算。仅放电时准确，充电时不显示百分比。",
            foreground=C["muted"], wraplength=500, justify="left")
        self.battery_hint.pack(fill="x", pady=(10, 0))

    def _build_control_section(self, outer):
        C = self.palette
        ttk.Label(outer, text="性能设置", font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        ttk.Label(outer, text="设备参数 / DPI & REPORT RATE", foreground=C["muted"]).pack(anchor="w", pady=(6, 20))
        ttk.Separator(outer).pack(fill="x")

        # DPI
        dpi_row = ttk.Frame(outer)
        dpi_row.pack(fill="x", pady=(20, 20))
        dpi_row.columnconfigure(1, weight=1)
        ttk.Label(dpi_row, text="01 / DPI", width=12, font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.dpi_var = tk.StringVar(value="—")
        self.dpi_combo = ttk.Combobox(dpi_row, textvariable=self.dpi_var, width=10,
                                      state="readonly")
        self.dpi_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16))
        self.dpi_set_btn = ttk.Button(dpi_row, text="设置 DPI", width=12, style="Accent.TButton", command=self.apply_dpi)
        self.dpi_set_btn.grid(row=0, column=2)
        ttk.Separator(outer).pack(fill="x")

        # 轮询率
        rate_row = ttk.Frame(outer)
        rate_row.pack(fill="x", pady=20)
        rate_row.columnconfigure(1, weight=1)
        ttk.Label(rate_row, text="02 / 轮询率", width=12, font=("Microsoft YaHei UI", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.rate_var = tk.StringVar(value="—")
        self.rate_combo = ttk.Combobox(rate_row, textvariable=self.rate_var, width=10,
                                       state="readonly")
        self.rate_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16))
        self.rate_set_btn = ttk.Button(rate_row, text="设置轮询率", width=12, style="Accent.TButton", command=self.apply_rate)
        self.rate_set_btn.grid(row=0, column=2)
        ttk.Separator(outer).pack(fill="x")

        self.ctrl_note = tk.Label(outer, text="等待读取性能参数…", anchor="w",
                                  bg=C["bg"], fg=C["muted"], justify="left",
                                  wraplength=500, font=("Microsoft YaHei UI", 10))
        self.ctrl_note.pack(fill="x", pady=(16, 0))

    def _build_devlog_section(self, parent):
        C = self.palette
        ttk.Label(parent, text="开发者日志", font=("Microsoft YaHei UI", 20, "bold")).pack(anchor="w")
        ttk.Label(parent, text="诊断 / HID++", foreground=C["muted"]).pack(anchor="w", pady=(6, 16))
        ttk.Separator(parent).pack(fill="x", pady=(0, 12))
        self.devlog_txt = tk.Text(parent, bg=C["bg"], fg=C["text"],
                                  font=("Consolas", 10), wrap="word", height=10,
                                  relief="flat", borderwidth=0, highlightthickness=0,
                                  selectbackground=C["text"], selectforeground=C["bg"],
                                  padx=0, pady=4)
        self.devlog_txt.pack(fill="both", expand=True)
        self.devlog_txt.config(state="disabled")
        self._refresh_devlog()

    def _refresh_devlog(self):
        lines = ["Logitech G903 · 开发者日志",
                 f"时间：{time.strftime('%Y-%m-%d %H:%M:%S')}", ""]
        info = self._last_info
        if info:
            lines.append(f"通道：{info['channel']}")
            lines.append(f"PID：0x{info['pid']:04X}")
            lines.append(f"原始响应字节：{' '.join(info['raw'])}")
            lines.append(f"本次采样：{info['values']}")
            lines.append(f"充电状态：{bat.BATTERY_STATUS_LABEL.get(info.get('status'), info.get('status'))}")
        ctrl = self._last_ctrl
        if ctrl:
            lines.append("")
            lines.append(f"当前 DPI：{ctrl['current_dpi']}")
            hz = ctrl['report_rate_hz']
            lines.append(f"当前轮询率：{ctrl['report_rate_ms']}ms ({hz if hz else '未知'}Hz)")
        lines.append("")
        lines.append("HID++ 常量：VID=0x046D  REPORT_ID=0x11")
        lines.append("feature：0x1001 电量电压 / 0x2201 DPI / 0x8060 轮询率 / 0x8100 板载模式")
        lines.append(f"历史 CSV：{bat.HISTORY_CSV}")
        self.devlog_txt.config(state="normal")
        self.devlog_txt.delete("1.0", "end")
        self.devlog_txt.insert("1.0", "\n".join(lines))
        self.devlog_txt.config(state="disabled")

    def _build_footer(self, outer):
        C = self.palette
        footer = ttk.Frame(outer)
        footer.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Separator(footer).pack(fill="x", pady=(0, 8))
        self.note_var = tk.StringVar(value="等待读取…")
        self.note_lbl = tk.Label(footer, textvariable=self.note_var, anchor="w",
                                 justify="left", font=("Microsoft YaHei UI", 10),
                                 bg=C["bg"], fg=C["muted"], wraplength=500)
        self.note_lbl.pack(fill="x")
        meta = ttk.Frame(footer)
        meta.pack(fill="x", pady=(10, 0))
        ttk.Label(meta, text="G903 / 设备监测",
                  foreground=C["muted"], font=("Microsoft YaHei UI", 9)).pack(side="left")
        ttk.Label(meta, text="F5 / 手动刷新",
                  foreground=C["muted"], font=("Microsoft YaHei UI", 9)).pack(side="right")

    def _on_close(self):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)
            self.after_id = None
        self.wave_bar.destroy()
        self.root.destroy()

    def _resize_text(self, event):
        width = max(200, event.width - 56)
        self.note_lbl.configure(wraplength=width)
        self.battery_hint.configure(wraplength=width)
        self.ctrl_note.configure(wraplength=width)

    def _set_note(self, text, warn=False):
        C = self.palette
        self.note_var.set(text)
        self.note_lbl.config(fg=C["warn"] if warn else C["muted"])

    # ---------- 读数 ----------

    def read_now(self):
        C = self.palette
        if self.running:
            return
        self.running = True
        self._set_note("读取中…")

        def worker():
            info, summary, err = bat.read_once()
            ctrl, cerr = _read_control()

            def done():
                self.running = False
                if err and cerr:
                    self._show_error(err)
                    return
                if not err:
                    self.apply_battery(info, summary)
                else:
                    self._show_error(err)
                if not cerr:
                    self.apply_control(ctrl)
                else:
                    self.ctrl_note.config(text=cerr, fg=C["warn"])
            try:
                self.root.after(0, done)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def apply_battery(self, info, summary):
        C = self.palette
        self.channel_var.set(f"{info['channel']} 连接")
        self.voltage_var.set(f"电压 {info['voltage']} mV")
        status = info.get("status", bat.BATTERY_DISCHARGING)
        label = bat.BATTERY_STATUS_LABEL.get(status, status)
        if status != bat.BATTERY_DISCHARGING:
            self.charging_var.set(f"● {label}")
            self.charging_lbl.config(fg=C["warn"])
        else:
            self.charging_var.set(f"● {label}")
            self.charging_lbl.config(fg=C["accent"])
        percent = info["percent"]
        if status == bat.BATTERY_FULL:
            self.wave_bar.set_percent(100)
        else:
            self.wave_bar.set_percent(percent)
        if status == bat.BATTERY_FULL:
            self.percent_var.set("100%")
        elif percent is None:
            self.percent_var.set("—")
        else:
            self.percent_var.set(f"{percent}%")
        self.time_var.set(f"更新于 {time.strftime('%H:%M:%S')}")
        self._last_info = dict(info)
        self._refresh_devlog()

    def apply_control(self, ctrl):
        C = self.palette
        self._last_ctrl = dict(ctrl)
        self.dpi_combo["values"] = [str(v) for v in ctrl["dpi_list"]]
        self.dpi_var.set(str(ctrl["current_dpi"]))
        rate_items = [f"{ms}ms ({ctl.MS_TO_HZ[ms]}Hz)" for ms in ctrl["report_rate_list_ms"]]
        self.rate_combo["values"] = rate_items
        hz = ctrl["report_rate_hz"]
        cur_rate_label = f"{ctrl['report_rate_ms']}ms" + (f" ({hz}Hz)" if hz else "")
        self.rate_var.set(cur_rate_label)
        self.ctrl_note.config(
            text=f"DPI 范围 {min(ctrl['dpi_list'])}~{max(ctrl['dpi_list'])}，"
                 f"当前 {ctrl['current_dpi']}；轮询率当前 {hz if hz else '未知'}Hz。",
            fg=C["muted"])
        self._set_note("已更新")
        self._refresh_devlog()

    # ---------- 设置写入 ----------

    def apply_dpi(self):
        C = self.palette
        val = self.dpi_var.get()
        try:
            dpi = int(val)
        except ValueError:
            messagebox.showwarning("DPI", "请输入有效 DPI 数值")
            return
        if not self._last_ctrl:
            messagebox.showwarning("DPI", "设备尚未读取到支持列表，请连接设备后稍候。")
            return
        if dpi not in self._last_ctrl["dpi_list"]:
            messagebox.showwarning("DPI", f"{dpi} 不在设备支持列表内，已取消。")
            return
        self.ctrl_note.config(text=f"正在设置 DPI {dpi}…", fg=C["muted"])
        self._run_write(lambda: _apply_dpi(dpi), f"DPI 已设置为 {dpi}")

    def apply_rate(self):
        C = self.palette
        label = self.rate_var.get()
        try:
            ms = int(label.split("ms")[0].strip())
        except (ValueError, IndexError):
            messagebox.showwarning("轮询率", "请选择有效轮询率")
            return
        if ms not in ctl.MS_TO_HZ:
            messagebox.showwarning("轮询率", f"{ms}ms 不是有效的轮询率间隔")
            return
        self.ctrl_note.config(text=f"正在设置轮询率 {ms}ms…", fg=C["muted"])
        self._run_write(lambda: _apply_rate(ms), f"轮询率已设置为 {ctl.MS_TO_HZ[ms]}Hz")

    def _run_write(self, fn, ok_msg):
        C = self.palette
        def worker():
            err = fn()
            def done():
                if err:
                    self.ctrl_note.config(text=err, fg=C["warn"])
                    messagebox.showerror("设置失败", err)
                else:
                    self.ctrl_note.config(text=ok_msg, fg=C["accent"])
                    self.read_now()
            try:
                self.root.after(0, done)
            except Exception:
                pass
        threading.Thread(target=worker, daemon=True).start()

    def _show_error(self, err):
        C = self.palette
        if "接口" in err or "无响应" in err or "不支持" in err:
            msg = "请开启鼠标并检查接收器或 USB 连接，稍后将自动重试。"
        else:
            msg = "读取失败，请重试。"
        self.channel_var.set("连接异常")
        self.wave_bar.pause()
        self.charging_var.set("读取失败" if self._last_info else "未获得读数")
        self.charging_lbl.config(fg=C["warn"])
        self._set_note(f"{msg}\n{err}", warn=True)



    # ---------- 自动刷新（固定 10 秒） ----------

    def _tick(self):
        self.after_id = None
        self.read_now()
        self.after_id = self.root.after(AUTO_REFRESH_MS, self._tick)

def main():
    root = tk.Tk()
    BatteryApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
