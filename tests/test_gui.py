"""Run with: python -m tests.test_gui (no hardware access or history writes)."""
import tkinter as tk
import time
import math
from unittest.mock import patch
from g903_app import g903_control_gui as control_gui
from g903_app.g903_cassette_gui import CassetteApp
from g903_battery import BATTERY_CHARGING, BATTERY_DISCHARGING, BATTERY_FULL


def check_app(app_class):
    root = tk.Tk()
    root.withdraw()
    control_root = tk.Toplevel(root)
    control_root.withdraw()
    control_root.after = lambda *_args: None
    info = dict(channel="无线", voltage=3800, percent=60, charging=False,
                values=[3799, 3800, 3801], pid=0xC539, raw=["0x11"])
    try:
        control = app_class(control_root)
        assert control_root.bind("<F5>")
        def find_nb(w):
            for c in w.winfo_children():
                if isinstance(c, tk.ttk.Notebook):
                    return c
                r = find_nb(c)
                if r:
                    return r
        nb = find_nb(control_root)
        assert nb is not None and len(nb.tabs()) == 3
        control.apply_battery(dict(info, status=BATTERY_DISCHARGING, percent=50), None)
        assert control.percent_var.get() == "50%"
        assert "开发者日志" in control.devlog_txt.get("1.0", "end")
        control.apply_battery(dict(info, status=BATTERY_CHARGING, percent=None), None)
        assert control.percent_var.get() == "—" and control.wave_bar._percent is None
        control.apply_battery(dict(info, status=BATTERY_FULL, percent=None), None)
        assert control.percent_var.get() == "100%" and control.wave_bar._percent == 100
        control.apply_battery(dict(info, status=BATTERY_DISCHARGING, percent=50), None)
        control._show_error("接口无响应")
        assert control.wave_bar._percent == 50 and control.wave_bar._anim_id is None
        if app_class is CassetteApp:
            assert control.voltage_meter.target_mv == 3800
            assert control.voltage_meter.anim_id is None
            assert "STALE" in control.voltage_meter.itemcget("status", "text")
            assert control.time_board.target == control.time_var.get().removeprefix("更新于 ")
        control.apply_control(dict(dpi_list=[400, 800, 1600, 3200], current_dpi=800,
                                   report_rate_list_ms=[1, 2, 4, 8],
                                   report_rate_ms=1, report_rate_hz=1000))
        control_root.deiconify()
        root.update()
        assert control_root.geometry().split("+")[0] == "680x760"
        control_root.geometry("560x740")
        root.update_idletasks()
        for tab in nb.tabs():
            nb.select(tab)
            root.update()
            assert nb.winfo_x() + nb.winfo_width() <= nb.master.winfo_width()
            page = nb.nametowidget(tab)
            for widget in page.winfo_children():
                assert widget.winfo_y() + widget.winfo_height() <= page.winfo_height()
            if app_class is CassetteApp:
                pending = list(page.winfo_children())
                while pending:
                    widget = pending.pop()
                    assert widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width()
                    assert widget.winfo_y() + widget.winfo_height() <= widget.master.winfo_height()
                    pending.extend(widget.winfo_children())
        footer = control.note_lbl.master
        assert footer.winfo_y() + footer.winfo_height() <= footer.master.winfo_height()
        nb.select(0)
        control.apply_battery(dict(info, status=BATTERY_FULL, percent=None), None)
        root.update()
        if app_class is control_gui.BatteryApp:
            hero = control.wave_bar.master
            reading = hero.winfo_children()[0]
            assert reading.winfo_x() + reading.winfo_width() <= control.wave_bar.winfo_x()
            reading_center = reading.winfo_y() + reading.winfo_height() / 2
            wave_center = control.wave_bar.winfo_y() + control.wave_bar.winfo_height() / 2
            assert abs(reading_center - wave_center) <= 1
        else:
            gauge = control.wave_bar.master
            reading = control.percent_lbl.master
            assert reading.winfo_x() + reading.winfo_width() <= gauge.winfo_x()
            assert control.percent_lbl.winfo_width() >= control.percent_lbl.winfo_reqwidth()
            reading_center = reading.winfo_y() + reading.winfo_height() / 2
            gauge_center = gauge.winfo_y() + gauge.winfo_height() / 2
            assert abs(reading_center - gauge_center) <= 1
            meter = control.voltage_meter
            clock = control.time_board.master
            assert meter.master is clock.master
            assert meter.winfo_y() == clock.winfo_y()
            assert meter.winfo_x() + meter.winfo_width() <= clock.winfo_x()
        hint = control.battery_hint
        assert hint.master.winfo_height() - hint.winfo_y() - hint.winfo_height() <= 16
        nb.select(1)
        root.update()
        for widget in (control.dpi_combo, control.rate_combo,
                       control.dpi_set_btn, control.rate_set_btn):
            assert widget.winfo_x() + widget.winfo_width() <= widget.master.winfo_width()
        assert control.dpi_combo.winfo_x() == control.rate_combo.winfo_x()
        if app_class is control_gui.BatteryApp:
            assert control.dpi_set_btn.winfo_x() == control.rate_set_btn.winfo_x()
        else:
            control._set_note("连接异常", warn=True)
            assert control.warn_lamp.itemcget(control._warn_dot, "fill") == "#FF4C3D"
        control._set_note("连接异常", warn=True)
        assert control.note_lbl.cget("fg") == control.palette["warn"]
        writes = []
        control._run_write = lambda fn, message: writes.append(message)
        control.dpi_var.set("1600")
        control.dpi_set_btn.invoke()
        control.rate_var.set("2ms (500Hz)")
        control.rate_set_btn.invoke()
        assert writes == ["DPI 已设置为 1600", "轮询率已设置为 500Hz"]
        print(f"{app_class.__name__} GUI checks passed")
    finally:
        root.destroy()


def main():
    for app_class in (control_gui.BatteryApp, CassetteApp):
        check_app(app_class)
    for method in ("read_now", "apply_control", "apply_dpi",
                   "apply_rate", "_run_write", "_tick"):
        assert getattr(CassetteApp, method) is getattr(control_gui.BatteryApp, method)
    check_animations()


def check_animations():
    root = tk.Tk()
    errors = []
    root.report_callback_exception = lambda *args: errors.append(args)
    with patch.object(CassetteApp, "read_now", lambda self: None):
        control = CassetteApp(root)
    try:
        root.update()
        for index in (1, 2, 0, 1, 2):
            control._select_page(index)
        control._set_note("旧提示")
        control._set_note("就绪")
        deadline = time.monotonic() + 0.4
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert control.notebook.index("current") == 2
        assert not control.noise.winfo_ismapped()
        assert control._note_display.get() == control.note_var.get() == "就绪"
        assert not control._screen_ids and not control._note_ids
        info = dict(channel="无线", voltage=3900, percent=70, status=BATTERY_DISCHARGING,
                    values=[3899, 3900, 3901], pid=0xC539, raw=["0x11"])
        control.apply_battery(info, None)
        control.time_board.set_time("23:59:59")
        root.update()
        assert control.voltage_meter.anim_id is not None
        assert control.time_board.anim_id is not None
        control.voltage_meter.set_voltage(4186)
        control.time_board.set_time("00:00:00")
        deadline = time.monotonic() + 0.7
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert control.voltage_meter.displayed_mv == control.voltage_meter.target_mv == 4186
        px, py, tx, ty = control.voltage_meter.coords("pointer")
        assert tx <= px and ty <= py
        assert math.isclose(math.hypot(tx - px, ty - py), control.voltage_meter._needle_length)
        assert control.time_board.displayed == control.time_board.target == "00:00:00"
        assert control.voltage_meter.anim_id is None and control.time_board.anim_id is None
        control.voltage_meter.set_voltage(4500)
        assert "OUT OF RANGE" in control.voltage_meter.itemcget("status", "text")
        for invalid in (float("nan"), float("inf")):
            try:
                control.voltage_meter.set_voltage(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("non-finite voltage accepted")
        try:
            control.time_board.set_time("24:00:00")
        except ValueError:
            pass
        else:
            raise AssertionError("invalid sample time accepted")
        assert control.time_board.target == "00:00:00"
        control.time_board.set_time("12:34:56")
        control._select_page(0)
        control._set_note("正在读取设备状态…")
        control._on_close()
        assert not control._animation_ids
        assert not root.tk.call("after", "info")
        assert not errors
        print("Cassette animation checks passed")
    finally:
        if not control._closed:
            control._on_close()


if __name__ == "__main__":
    main()
