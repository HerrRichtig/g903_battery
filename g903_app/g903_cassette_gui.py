"""独立的卡带 CRT 控制台；设备读写仍由 BatteryApp 完成。"""
import tkinter as tk
from tkinter import font as tkfont, ttk

from .g903_control_gui import AUTO_REFRESH_MS, BatteryApp
from .g903_battery_wave import BatteryWaveBar
from .analog_voltage import VoltageMeter
from .scoreboard_time import ScoreboardTime


C = {
    "bg": "#202925", "panel": "#07160F", "raised": "#35463B",
    "line": "#536F58", "text": "#B9F3A6", "muted": "#85A88B",
    "accent": "#83FF65", "warn": "#EABC64",
}
RED = "#FF4C3D"  # 仅用于警告指示灯。


class CassetteApp(BatteryApp):
    palette = C

    def __init__(self, root):
        self.root = root
        self.running = False
        self.after_id = None
        self._last_info = None
        self._last_ctrl = None
        self._closed = False
        self._animation_ids = set()
        self._screen_ids = set()
        self._note_ids = set()
        families = set(tkfont.families(root))
        self.mono = next((f for f in ("Terminal", "Fixedsys", "Consolas")
                          if f in families), "Courier")
        self.narrow = next((f for f in ("Bahnschrift SemiCondensed", "Bahnschrift",
                                      "Courier") if f in families), "Courier")
        root.title("G903 / 卡带 CRT 控制台")
        root.geometry("680x760")
        root.minsize(560, 740)
        root.configure(bg=C["bg"])
        self._apply_style(ttk.Style(root))

        outer = tk.Frame(root, bg=C["bg"], padx=12, pady=12)
        outer.pack(fill="both", expand=True)
        self._build_header(outer)
        self._build_footer(outer)
        body = tk.Frame(outer, bg=C["bg"])
        body.pack(fill="both", expand=True, pady=10)
        rail = tk.Frame(body, bg=C["bg"], width=104)
        rail.pack(side="left", fill="y", padx=(0, 10))
        rail.pack_propagate(False)
        self._label(rail, "CHANNEL", bg=C["bg"]).pack(anchor="w", pady=(0, 8))
        self.nav_buttons = []
        for index, (name, chinese) in enumerate((
                ("BATTERY", "电量"), ("CONTROL", "性能设置"),
                ("DIAGNOSTICS", "诊断日志"))):
            self._label(rail, f"0{index + 1} / {name}", size=8,
                        bg=C["bg"]).pack(anchor="w", pady=(8, 4))
            button = self._button(rail, chinese, lambda i=index: self._select_page(i))
            button.pack(fill="x", ipady=6)
            self.nav_buttons.append(button)
        self._label(rail, "SYNC / F5", bg=C["bg"]).pack(anchor="w", pady=(16, 4))
        self._button(rail, "读取", self.read_now).pack(fill="x", ipady=8)
        self._label(rail, "HID++\n10 SEC AUTO", bg=C["bg"],
                    size=9).pack(anchor="w", pady=8)
        self._label(rail, "TYPE 903\nSIDE A", bg=C["bg"],
                    size=8).pack(side="bottom", anchor="w", pady=6)

        bezel = tk.Frame(body, bg=C["line"], bd=4, relief="sunken")
        bezel.pack(side="left", fill="both", expand=True)
        self.screen_title = tk.StringVar(value="01 / BATTERY")
        self._label(bezel, variable=self.screen_title, fg=C["accent"],
                    size=12).pack(fill="x", ipady=7)
        self.screen = tk.Frame(bezel, bg=C["panel"])
        self.screen.pack(fill="both", expand=True)
        self.notebook = ttk.Notebook(self.screen, style="CRT.TNotebook", takefocus=False)
        self.notebook.pack(fill="both", expand=True)
        self.pages = [tk.Frame(self.notebook, bg=C["panel"], padx=12, pady=10)
                      for _ in range(3)]
        for page, name in zip(self.pages, ("BATTERY", "CONTROL", "DIAGNOSTICS")):
            self.notebook.add(page, text=name)
        self._build_battery_section(self.pages[0])
        self._build_control_section(self.pages[1])
        self._build_devlog_section(self.pages[2])
        self.noise = tk.Canvas(self.screen, bg=C["panel"], highlightthickness=0,
                               takefocus=False)
        self.notebook.bind("<<NotebookTabChanged>>", self._page_changed)
        self.screen.bind("<Configure>", self._resize_text)
        root.bind("<F5>", lambda event: self.read_now())
        root.bind("<Control-Tab>", lambda event: self._cycle_page(1))
        root.bind("<Control-Shift-Tab>", lambda event: self._cycle_page(-1))
        root.bind("<Control-ISO_Left_Tab>", lambda event: self._cycle_page(-1))
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._page_changed()
        self._screen_effect(boot=True)
        self._set_note("系统启动，等待读取…")
        self._schedule(100, self.read_now)
        self.after_id = root.after(AUTO_REFRESH_MS, self._tick)

    def _apply_style(self, style):
        style.theme_use("clam")
        style.configure("CRT.TNotebook", background=C["panel"], borderwidth=0,
                        bordercolor=C["line"], lightcolor=C["line"], darkcolor=C["panel"])
        style.layout("CRT.TNotebook.Tab", [])
        style.configure("CRT.TNotebook", tabmargins=0)
        style.configure("CRT.TCombobox", font=(self.mono, 12), padding=7,
                        fieldbackground=C["panel"], background=C["raised"],
                        foreground=C["accent"], arrowcolor=C["accent"],
                        bordercolor=C["line"], lightcolor=C["line"],
                        darkcolor=C["panel"], selectbackground=C["accent"],
                        selectforeground=C["panel"])
        style.map("CRT.TCombobox",
                  fieldbackground=[("readonly", C["panel"]), ("disabled", C["bg"])],
                  foreground=[("disabled", C["muted"]), ("readonly", C["accent"])],
                  bordercolor=[("focus", C["accent"])])
        style.configure("CRT.Vertical.TScrollbar", background=C["raised"],
                        troughcolor=C["panel"], arrowcolor=C["accent"],
                        bordercolor=C["line"], lightcolor=C["line"], darkcolor=C["panel"])
        style.map("CRT.Vertical.TScrollbar", background=[("active", C["line"])])
        self.root.option_add("*TCombobox*Listbox.background", C["panel"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["accent"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["accent"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", C["panel"])

    def _label(self, parent, text=None, *, variable=None, fg=None, bg=None, size=10):
        return tk.Label(parent, text=text, textvariable=variable,
                        bg=bg or C["panel"], fg=fg or C["muted"],
                        font=(self.narrow, size, "bold"), anchor="w", justify="left")

    def _button(self, parent, text, command):
        return tk.Button(parent, text=text, command=command, takefocus=True,
                         font=("Microsoft YaHei UI", 10, "bold"),
                         bg=C["raised"], fg=C["text"], activebackground=C["accent"],
                         activeforeground=C["panel"], disabledforeground=C["muted"],
                         relief="raised", bd=4, padx=6, pady=6,
                         highlightthickness=1, highlightbackground=C["line"],
                         highlightcolor=C["accent"], cursor="hand2")

    def _build_header(self, outer):
        plate = tk.Frame(outer, bg=C["raised"], bd=3, relief="raised")
        plate.pack(fill="x")
        self._label(plate, "G903", bg=C["raised"], fg=C["accent"], size=30).pack(
            side="left", padx=10, pady=6)
        titles = tk.Frame(plate, bg=C["raised"])
        titles.pack(side="left", fill="x", expand=True, padx=8)
        self._label(titles, "CASSETTE / TELEMETRY", bg=C["raised"],
                    fg=C["text"], size=13).pack(anchor="w")
        tk.Label(titles, text="卡带控制台 · LIGHTSPEED", bg=C["raised"],
                 fg=C["muted"], font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        self._label(plate, "●\n903–A", bg=C["raised"],
                    fg=C["warn"], size=10).pack(side="right", padx=10)

    def _build_footer(self, outer):
        footer = tk.Frame(outer, bg=C["panel"], bd=3, relief="sunken", padx=9, pady=7)
        footer.pack(side="bottom", fill="x")
        lamps = tk.Frame(footer, bg=C["panel"])
        lamps.pack(fill="x")
        self._label(lamps, "● SYSTEM", fg=C["accent"], size=9).pack(side="left")
        self.warn_lamp = tk.Canvas(lamps, width=14, height=14, bg=C["panel"],
                                   highlightthickness=0)
        self.warn_lamp.pack(side="left", padx=(14, 4))
        self._warn_dot = self.warn_lamp.create_oval(3, 3, 11, 11,
                                                   fill=C["raised"], outline=C["line"])
        self._label(lamps, "WARN", size=9).pack(side="left")
        self._label(lamps, "F5 / SYNC", size=9).pack(side="right")
        self.channel_var = tk.StringVar(value="正在连接鼠标…")
        self.channel_lbl = tk.Label(footer, textvariable=self.channel_var,
                                    bg=C["panel"], fg=C["accent"], anchor="w",
                                    font=("Microsoft YaHei UI", 9), justify="left")
        self.channel_lbl.pack(fill="x", pady=(5, 2))
        self.note_var = tk.StringVar(value="等待读取…")
        self._note_display = tk.StringVar(value="")
        self.note_lbl = tk.Label(footer, textvariable=self._note_display,
                                 anchor="nw", justify="left", bg=C["panel"],
                                 fg=C["muted"], font=("Microsoft YaHei UI", 9),
                                 wraplength=480)
        self.note_lbl.pack(fill="x")
        footer.bind("<Configure>", self._resize_footer)

    def _module(self, parent, title, chinese):
        self._label(parent, title, fg=C["accent"], size=12).pack(fill="x")
        tk.Label(parent, text=chinese, bg=C["panel"], fg=C["muted"],
                 anchor="w", font=("Microsoft YaHei UI", 9)).pack(fill="x", pady=(2, 8))
        tk.Frame(parent, bg=C["line"], height=2).pack(fill="x", pady=(0, 10))

    def _build_battery_section(self, parent):
        self._module(parent, "CHARGE / VOLTAGE", "电池仪表 · 电压估算")
        # 先保留采样信息，仪表区使用剩余空间。
        details = tk.Frame(parent, bg=C["panel"])
        details.pack(side="bottom", fill="x", pady=(8, 0))
        self.voltage_var = tk.StringVar(value="电压 —")
        self.time_var = tk.StringVar(value="尚未更新")
        self.battery_hint = tk.Label(details,
            text="电量由电压估算。仅放电时准确，充电时不显示百分比。",
            bg=C["panel"], fg=C["muted"], font=("Microsoft YaHei UI", 9),
            justify="left", anchor="w", wraplength=340)
        self.battery_hint.pack(fill="x", pady=(5, 0))
        reading = tk.Frame(parent, bg=C["panel"])
        reading.pack(fill="x", pady=(0, 8))
        reading.columnconfigure(0, weight=1)
        reading.rowconfigure(0, weight=1)
        numbers = tk.Frame(reading, bg=C["panel"])
        numbers.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self._label(numbers, "CAPACITY / %", size=9).pack(anchor="w")
        self.percent_var = tk.StringVar(value="—")
        self.percent_lbl = tk.Label(numbers, textvariable=self.percent_var,
                                    bg=C["panel"], fg=C["accent"],
                                    font=(self.mono, 46, "bold"), anchor="w")
        self.percent_lbl.pack(fill="x", pady=2)
        self.charging_var = tk.StringVar(value="等待读取")
        self.charging_lbl = tk.Label(numbers, textvariable=self.charging_var,
                                     bg=C["panel"], fg=C["muted"], anchor="w",
                                     font=("Microsoft YaHei UI", 10))
        self.charging_lbl.pack(fill="x")
        gauge = tk.Frame(reading, bg=C["panel"])
        gauge.grid(row=0, column=1, sticky="e")
        self._label(gauge, "LEVEL", size=8).pack()
        self.wave_bar = BatteryWaveBar(gauge, width=38, height=92,
                                       track="#172D1E", border=C["line"],
                                       fill=C["accent"], low_fill=C["warn"], bg=C["panel"])
        self.wave_bar.pack()
        self._label(gauge, "0–100", size=8).pack()
        instruments = tk.Frame(parent, bg=C["panel"])
        instruments.pack(fill="both", expand=True, pady=(2, 4))
        instruments.columnconfigure(0, weight=1, uniform="instrument")
        instruments.columnconfigure(1, weight=1, uniform="instrument")
        instruments.rowconfigure(0, weight=1)
        self.voltage_meter = VoltageMeter(instruments, mono=self.mono, narrow=self.narrow,
                                          height=225, width=1)
        self.voltage_meter.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        clock = tk.Frame(instruments, bg=C["raised"], bd=2, relief="sunken", height=225)
        clock.grid(row=0, column=1, sticky="ew", padx=(4, 0))
        clock.grid_propagate(False)
        clock.columnconfigure(0, weight=1)
        clock.rowconfigure(1, weight=1)
        self._label(clock, "LAST SAMPLE", size=10, bg=C["raised"],
                    fg=C["accent"]).grid(row=0, column=0, sticky="w", padx=8, pady=(12, 0))
        self.time_board = ScoreboardTime(clock, width=1)
        self.time_board.grid(row=1, column=0, sticky="ew", padx=6)
        tk.Label(clock, text="更新于 · 时 / 分 / 秒", bg=C["raised"], fg=C["muted"],
                 font=("Microsoft YaHei UI", 8)).grid(row=2, column=0, sticky="w", padx=8, pady=(0, 12))

    def apply_battery(self, info, summary):
        super().apply_battery(info, summary)
        self.voltage_meter.set_voltage(info["voltage"])
        self.time_board.set_time(self.time_var.get().removeprefix("更新于 "))

    def _show_error(self, err):
        super()._show_error(err)
        self.voltage_meter.pause()
        self.time_board.finish()

    def _build_control_section(self, parent):
        self._module(parent, "PARAMETER / WRITE", "性能设置 · 写入后读取设备确认")
        for tag, title, variable_name, combo_name, button_name, command in (
                ("01 / DPI", "鼠标灵敏度", "dpi_var", "dpi_combo", "dpi_set_btn", self.apply_dpi),
                ("02 / REPORT RATE", "轮询率", "rate_var", "rate_combo", "rate_set_btn", self.apply_rate)):
            module = tk.Frame(parent, bg=C["bg"], bd=2, relief="groove", padx=10, pady=8)
            module.pack(fill="x", pady=(6, 14))
            self._label(module, tag, bg=C["bg"], fg=C["accent"]).pack(anchor="w")
            tk.Label(module, text=title, bg=C["bg"], fg=C["muted"],
                     font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(0, 8))
            var = tk.StringVar(value="—")
            setattr(self, variable_name, var)
            self._label(module, "SET / CONFIRM", bg=C["bg"], size=8).pack(anchor="e")
            controls = tk.Frame(module, bg=C["bg"])
            controls.pack(fill="x")
            combo = ttk.Combobox(controls, textvariable=var, state="readonly", width=10,
                                 style="CRT.TCombobox", takefocus=True)
            combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
            setattr(self, combo_name, combo)
            button = self._button(controls, "设置 DPI" if variable_name == "dpi_var" else "设置轮询率", command)
            button.pack(side="right")
            setattr(self, button_name, button)
        self.ctrl_note = tk.Label(parent, text="等待读取性能参数…", anchor="w",
                                  bg=C["panel"], fg=C["muted"], justify="left",
                                  wraplength=340, font=("Microsoft YaHei UI", 9))
        self.ctrl_note.pack(fill="x", pady=4)

    def _build_devlog_section(self, parent):
        self._module(parent, "HID++ / DIAGNOSTICS", "诊断日志 · 当前采样及设备参数")
        self._label(parent, "READ ONLY / RAW RESPONSE", size=9).pack(fill="x", pady=(0, 6))
        well = tk.Frame(parent, bg=C["panel"])
        well.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(well, orient="vertical", style="CRT.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        self.devlog_txt = tk.Text(well, bg=C["panel"], fg=C["accent"],
                                  insertbackground=C["accent"], font=(self.mono, 10),
                                  wrap="char", width=1, height=1, relief="sunken", bd=2,
                                  highlightthickness=1, highlightcolor=C["accent"],
                                  highlightbackground=C["line"], padx=7, pady=7,
                                  selectbackground=C["accent"], selectforeground=C["panel"],
                                  yscrollcommand=scrollbar.set, takefocus=True)
        self.devlog_txt.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.devlog_txt.yview)
        self._refresh_devlog()
        self._label(parent, "VID 046D / REPORT 11", size=9).pack(fill="x", pady=(8, 0))

    def _resize_footer(self, event):
        width = max(120, event.width - 28)
        self.note_lbl.configure(wraplength=width)
        self.channel_lbl.configure(wraplength=width)

    def _resize_text(self, event):
        width = max(120, event.width - 28)
        self.battery_hint.configure(wraplength=width)
        self.ctrl_note.configure(wraplength=width)
        # 100% 在最小窗口仍完整；只调整字形，不改变数值。
        size = 46 if width >= 340 else 38
        self.percent_lbl.configure(font=(self.mono, size, "bold"))

    def _schedule(self, delay, callback, group=None):
        """一个集合记录所有本模块回调，子集合用于取消前次动效。"""
        if self._closed:
            return None
        def run():
            self._animation_ids.discard(identifier)
            if group is not None:
                group.discard(identifier)
            if not self._closed:
                callback()
        identifier = self.root.after(delay, run)
        if identifier is not None:
            self._animation_ids.add(identifier)
            if group is not None:
                group.add(identifier)
        return identifier

    def _cancel(self, identifiers):
        for identifier in tuple(identifiers):
            self.root.after_cancel(identifier)
            self._animation_ids.discard(identifier)
        identifiers.clear()

    def _set_note(self, text, warn=False):
        super()._set_note(text, warn=warn)
        self.warn_lamp.itemconfigure(self._warn_dot, fill=RED if warn else C["raised"])
        self._cancel(self._note_ids)
        # 警告立即完整显示；常规提示在独立显示变量上打字。
        self._note_display.set(text if warn else "")
        if not warn:
            def type_next(count=1):
                self._note_display.set(text[:count])
                if count < len(text):
                    self._schedule(24, lambda: type_next(count + 1), self._note_ids)
            type_next()

    def _select_page(self, index):
        if self.notebook.index("current") == index:
            return
        self.notebook.select(index)
        self._page_changed()
        self._screen_effect()

    def _cycle_page(self, step):
        index = (self.notebook.index("current") + step) % 3
        self._select_page(index)
        self.nav_buttons[index].focus_set()
        return "break"

    def _page_changed(self, event=None):
        index = self.notebook.index("current")
        name = ("BATTERY", "CONTROL", "DIAGNOSTICS")[index]
        self.screen_title.set(f"0{index + 1} / {name}")
        for i, button in enumerate(self.nav_buttons):
            button.configure(relief="sunken" if i == index else "raised",
                             bg=C["accent"] if i == index else C["raised"],
                             fg=C["panel"] if i == index else C["text"])

    def _screen_effect(self, boot=False):
        self._cancel(self._screen_ids)
        self.noise.place(x=0, y=0, relwidth=1, relheight=1)
        tk.Misc.lift(self.noise)
        frames = 7 if boot else 4
        def frame(step=0):
            self.noise.delete("all")
            if step >= frames:
                self.noise.place_forget()
                return
            w, h = self.screen.winfo_width(), self.screen.winfo_height()
            self.noise.configure(bg="#244D2B" if boot and step % 2 == 0 else C["panel"])
            # 确定性雪花及步进扫描；无随机状态、无常驻动画。
            for y in range(0, h, 7):
                offset = (y * 13 + step * 47) % max(1, w)
                self.noise.create_line(offset, y, min(w, offset + 17 + y % 39), y,
                                       fill=C["line"] if y % 3 else C["accent"])
            scan = h * (step + 1) / frames
            self.noise.create_rectangle(0, scan - 4, w, scan, fill=C["accent"], outline="")
            if boot:
                self.noise.create_text(16, 26, text="CRT / BOOT  ▪ ▪ ▪", anchor="w",
                                       font=(self.mono, 12), fill=C["accent"])
            self._schedule(45, lambda: frame(step + 1), self._screen_ids)
        frame()

    def _on_close(self):
        self._closed = True
        self._cancel(self._animation_ids)
        self._screen_ids.clear()
        self._note_ids.clear()
        super()._on_close()


def main():
    root = tk.Tk()
    CassetteApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
