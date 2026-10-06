"""采样时间计分板：七段数字与短暂翻牌过渡，不运行实时钟。"""
import re
import time
import tkinter as tk


SEGMENTS = {
    "0": "abcdef", "1": "bc", "2": "abdeg",
    "3": "abcdg", "4": "bcfg", "5": "acdfg", "6": "acdefg",
    "7": "abc", "8": "abcdefg", "9": "abcdfg", "-": "g",
}


class ScoreboardTime(tk.Canvas):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("width", 240)
        super().__init__(master, height=48, bg="#07160F",
                         highlightthickness=0, **kwargs)
        self.target = "--:--:--"
        self.displayed = self.target
        self.anim_id = None
        self._old = self.target
        self._progress = 1.0
        self.bind("<Configure>", lambda event: self._draw())
        self.bind("<Destroy>", self._on_destroy)

    def set_time(self, value):
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d", value):
            raise ValueError("sample time must be HH:MM:SS")
        if value == self.target:
            return
        self.finish()
        self._old, self.target = self.displayed, value
        self._started = time.monotonic()
        self._progress = 0.0
        self._draw()
        self.anim_id = self.after(16, self._animate)

    def finish(self):
        if self.anim_id is not None:
            self.after_cancel(self.anim_id)
            self.anim_id = None
        self.displayed = self.target
        self._progress = 1.0
        self._draw()

    def _animate(self):
        self.anim_id = None
        self._progress = min(1.0, (time.monotonic() - self._started) / 0.55)
        self._draw()
        if self._progress < 1:
            self.anim_id = self.after(16, self._animate)
        else:
            self.displayed = self.target

    def _on_destroy(self, event):
        if event.widget is self and self.anim_id is not None:
            self.after_cancel(self.anim_id)
            self.anim_id = None

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        # 六个独立数字窗，冒号固定；只翻动实际发生变化的数字。
        cell = min(38, (w - 16) / 7)
        x = (w - cell * 7) / 2
        digit_index = 0
        for index, char in enumerate(self.target):
            if char == ":":
                for y in (h * .36, h * .66):
                    self.create_oval(x + cell * .22, y - 2, x + cell * .22 + 4,
                                     y + 2, fill="#83FF65", outline="")
                x += cell / 2
                continue
            self.create_rectangle(x + 1, 2, x + cell - 2, h - 2,
                                  fill="#10241A", outline="#536F58")
            p = max(0.0, min(1.0, (self._progress * .55 - digit_index * .025) / .4))
            old = self._old[index]
            if old == char or self._progress >= 1:
                scale, visible = 1.0, char
            else:
                scale = abs(1 - 2 * p)
                visible = old if p < .5 else char
            self._digit(x + 5, cell - 12, h - 14, h / 2, scale, visible)
            self.create_line(x + 2, h / 2, x + cell - 3, h / 2,
                             fill="#07160F", width=1)
            x += cell
            digit_index += 1

    def _digit(self, x, width, height, cy, scale, char):
        points = {
            "a": (0, -1, 1, -1), "b": (1, -1, 1, 0),
            "c": (1, 0, 1, 1), "d": (0, 1, 1, 1),
            "e": (0, 0, 0, 1), "f": (0, -1, 0, 0), "g": (0, 0, 1, 0),
        }
        for segment, (x0, y0, x1, y1) in points.items():
            self.create_line(x + x0 * width, cy + y0 * height / 2 * scale,
                             x + x1 * width, cy + y1 * height / 2 * scale,
                             fill="#83FF65" if segment in SEGMENTS[char] else "#1D3926",
                             width=3, capstyle="projecting")
