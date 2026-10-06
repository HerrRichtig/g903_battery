"""卡带 CRT 电压表，无硬件依赖；所有调用应在 Tk 主线程进行。"""

import math
import numbers
import time
import tkinter as tk


C = {
    "bg": "#202925", "panel": "#07160F", "raised": "#35463B",
    "line": "#536F58", "text": "#B9F3A6", "muted": "#85A88B",
    "accent": "#83FF65", "warn": "#EABC64",
}
MIN_MV = 3300
MAX_MV = 4300
ANIMATION_SECONDS = 0.4


def voltage_fraction(millivolts):
    """将电压限制到固定量程，返回旋转刻度比例。"""
    return max(0.0, min(1.0, (millivolts - MIN_MV) / (MAX_MV - MIN_MV)))


class VoltageMeter(tk.Canvas):
    """固定 3.3—4.3 V 量程；target_mv 为采样值，displayed_mv 为针位。

    默认 230 × 225，可按布局填充宽度。None 清空采样；
    pause() 保留当前针位和最后采样，并标记 STALE。
    """

    def __init__(self, master, *, mono="Consolas", narrow="Bahnschrift",
                 height=225, **kwargs):
        kwargs.setdefault("width", 230)
        kwargs.setdefault("bg", C["bg"])
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("bd", 0)
        super().__init__(master, height=height, **kwargs)
        self.mono = mono
        self.narrow = narrow
        self.target_mv = None
        self.displayed_mv = None
        self.anim_id = None
        self._stale = False
        self._closed = False
        self._width = float(self.cget("width"))
        self._height = float(self.cget("height"))
        self.bind("<Configure>", self._resize, add="+")
        self.bind("<Destroy>", self._destroyed, add="+")
        self._redraw()

    def set_voltage(self, millivolts):
        """接受有限数值（mV）或 None；无效数值抛 ValueError。"""
        if self._closed:
            return
        if millivolts is not None:
            if isinstance(millivolts, bool) or not isinstance(millivolts, numbers.Number):
                raise ValueError("millivolts must be a finite number or None")
            try:
                millivolts = float(millivolts)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("millivolts must be a finite number") from exc
            if not math.isfinite(millivolts):
                raise ValueError("millivolts must be finite")
        self._cancel_animation()
        self.target_mv = millivolts
        self._stale = False
        if millivolts is None:
            self.displayed_mv = None
            self._draw_pointer()
            self._update_readout()
            return
        self._from_mv = MIN_MV if self.displayed_mv is None else self.displayed_mv
        self._to_mv = MIN_MV + voltage_fraction(millivolts) * (MAX_MV - MIN_MV)
        self.displayed_mv = self._from_mv
        self._started = time.monotonic()
        self._update_readout()
        self._draw_pointer()
        self.anim_id = self.after(16, self._animate)

    def pause(self):
        """停止动画，冻结当前位置；下次 set_voltage 从此位置继续。"""
        if self._closed:
            return
        self._cancel_animation()
        self._stale = self.target_mv is not None
        self._update_readout()

    def _cancel_animation(self):
        if self.anim_id is not None:
            self.after_cancel(self.anim_id)
            self.anim_id = None

    def _animate(self):
        self.anim_id = None
        if self._closed:
            return
        progress = min(1.0, (time.monotonic() - self._started) / ANIMATION_SECONDS)
        eased = progress * progress * (3.0 - 2.0 * progress)
        self.displayed_mv = (self._to_mv if progress == 1.0 else
                             self._from_mv + (self._to_mv - self._from_mv) * eased)
        self._draw_pointer()
        if progress < 1.0:
            self.anim_id = self.after(16, self._animate)

    def _destroyed(self, event):
        if event.widget is self:
            self._closed = True
            self._cancel_animation()

    def _resize(self, event):
        self._width, self._height = event.width, event.height
        self._redraw()

    def _redraw(self):
        self.delete("all")
        w, h = self._width, self._height
        # 转轴位于表盘右下；同时按宽、高留出外侧刻度和底部读数。
        self._pivot = (w - 36, h - 77)
        self._radius = max(0.0, min(w - 70, h - 111))
        self._needle_length = max(0.0, self._radius - 13)
        px, py = self._pivot
        radius = self._radius
        self.create_rectangle(3, 3, w - 3, h - 3, fill=C["raised"],
                              outline=C["line"], width=1)
        self.create_rectangle(8, 8, w - 8, h - 8, fill=C["panel"],
                              outline=C["bg"], width=3)
        self.create_line(10, h - 10, w - 10, h - 10, w - 10, 10,
                         fill=C["line"])
        self.create_line(10, h - 10, 10, 10, w - 10, 10, fill="#030B07", width=2)
        self.create_arc(px - radius, py - radius, px + radius, py + radius,
                        start=90, extent=90, style=tk.ARC, outline=C["muted"],
                        tags="scale_arc")
        self.create_line(px - radius, py, px, py, px, py - radius,
                         fill=C["line"], tags="radial_baseline")
        major_step = 5 if w >= 260 else 10
        for index in range(21):
            angle = math.pi - index / 20 * math.pi / 2
            dx, dy = math.cos(angle), -math.sin(angle)
            major = index % major_step == 0
            length = 10 if major else 4
            self.create_line(px + (radius - length) * dx,
                             py + (radius - length) * dy,
                             px + radius * dx, py + radius * dy,
                              fill=C["accent"] if major else C["muted"],
                              width=2 if major else 1)
            if major:
                self.create_text(px + (radius + 15) * dx,
                                 py + (radius + 15) * dy,
                                 text=f"{3.3 + index / 20:.2f}" if major_step == 5
                                 else f"{3.3 + index / 20:.1f}",
                                 tags="scale_label", fill=C["text"],
                                 font=(self.mono, 9))
        self.create_text(px - 40, py - 25, text="DC VOLTS", fill=C["accent"],
                         tags="meter_label", font=(self.narrow, 10, "bold"))
        self.create_text(w / 2, h - 54, tags="reading",
                         fill=C["text"], font=(self.mono, 12))
        self.create_text(w / 2, h - 37, anchor="n", tags="status",
                         fill=C["warn"], font=(self.narrow, 9, "bold"))
        self.create_line(0, 0, 0, 0, tags="pointer", fill=C["warn"], width=2)
        self.create_oval(px - 8, py - 8, px + 8, py + 8, tags="pivot",
                         fill=C["bg"], outline=C["line"], width=2)
        self.create_oval(px - 4, py - 4, px + 4, py + 4, tags="pivot",
                         fill=C["warn"], outline=C["muted"])
        self._draw_pointer()
        self._update_readout()

    def _draw_pointer(self):
        if self.displayed_mv is None:
            self.itemconfigure("pointer", state="hidden")
            return
        px, py = self._pivot
        angle = math.pi - voltage_fraction(self.displayed_mv) * math.pi / 2
        length = self._needle_length
        self.coords("pointer", px, py,
                    px + length * math.cos(angle), py - length * math.sin(angle))
        self.itemconfigure("pointer", state="normal")

    def _update_readout(self):
        if self.target_mv is None:
            reading, status = "— V", "NO SAMPLE"
        else:
            # 数字始终显示最后的真实采样，不使用动画插值值。
            reading = f"{self.target_mv / 1000:.3f} V"
            flags = []
            if self._stale:
                flags.append("STALE")
            if not MIN_MV <= self.target_mv <= MAX_MV:
                flags.append("OUT OF RANGE")
            status = "\n".join(flags)
        self.itemconfigure("reading", text=reading)
        self.itemconfigure("status", text=status,
                           fill=C["warn"] if self.target_mv is not None else C["muted"])
