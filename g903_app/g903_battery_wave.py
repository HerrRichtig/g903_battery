"""竖向长方形波浪液位控件（两个 GUI 共用）。

只把电量百分比可视化，不参与电量计算，也不写任何数据。
使用标准库 tkinter.Canvas，无额外依赖。

关键设计：
- 轨道与边框只绘制一次；每帧只删除并重画带 ``wave`` 标签的液面多边形。
- 液面由两层不同相位的正弦波构成，振幅约为条高的 2% 和 1%。
- 液面高度 = percent/100 映射到底部至顶部，绘制前限制到 0~100。
- 0% 只显示空轨道；100% 填满至顶部并裁住波峰；None 显示空轨道。
- 正常值在 0% 与 100% 之间时波动；边界值保持静止。
- 读取失败由调用方调用 pause()，保留最后液面但暂停波动。
"""
import math

import tkinter as tk

WAVE_TAG = "wave"
FRAME_MS = 33          # 约 30 FPS
PHASE_STEP = 0.22      # 每帧相位推进量（弧度）
SAMPLES = 48           # 液面上沿采样点数
DEFAULT_WIDTH = 76     # 控件默认宽度（像素）
DEFAULT_HEIGHT = 132   # 控件默认高度（像素）


class BatteryWaveBar(tk.Canvas):
    """以液面高度表示电量的波浪容器。

    颜色参数允许两个窗口按各自主题覆盖；百分比为 ``None`` 时显示空轨道。
    """

    def __init__(self, master, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT, track="#1E2128",
                 border="#333845", fill="#3FA9F5", low_fill="#E2894A",
                 low_threshold=20, bg="#17191E", **kwargs):
        super().__init__(master, width=width, height=height, bg=bg,
                         highlightthickness=0, **kwargs)
        self._track = track
        self._border = border
        self._fill = fill
        self._low_fill = low_fill
        self._low_threshold = low_threshold
        self._percent = None       # 当前有效百分比（0~100）
        self._phase = 0.0          # 波浪相位
        self._anim_id = None       # 待执行的 after 回调 id
        self._prev_width = 0
        self.bind("<Configure>", self._on_resize)
        self.bind("<Destroy>", self._on_destroy)

    # ----- 对外接口 -----

    def set_percent(self, percent):
        """设置当前值；``None`` 清空液面并停止动画。"""
        self._percent = None if percent is None else max(0.0, min(100.0, float(percent)))
        self._redraw()
        if self._percent is not None and 0 < self._percent < 100:
            self._ensure_animating()
        else:
            self._pause()

    def pause(self):
        """暂停动画并保留最后显示的液面。"""
        self._pause()

    def _ensure_animating(self):
        if self._anim_id is None:
            self._anim_id = self.after(FRAME_MS, self._advance)

    def _pause(self):
        if self._anim_id is not None:
            try:
                self.after_cancel(self._anim_id)
            except Exception:
                pass
            self._anim_id = None

    # ----- 绘制 -----

    def _on_resize(self, event):
        if event.width != self._prev_width:
            self._prev_width = event.width
            self._redraw()

    def _on_destroy(self, _event):
        if _event.widget is self:
            self._pause()

    def _redraw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 2 or h <= 2:
            self._prev_width = 0
            return
        # 轨道与边框只绘制一次（每次重画时新建）
        self.create_rectangle(0, 0, w - 1, h - 1, outline=self._border,
                              width=1, fill=self._track)
        percent = self._percent
        if percent is None:
            return
        if percent <= 0:
            return
        if percent >= 100:
            self.create_rectangle(1, 1, w - 2, h - 2, fill=self._color_for(percent),
                                  outline="", tags=WAVE_TAG)
            return
        self._draw_wave(w, h, percent / 100.0)

    def _color_for(self, percent):
        if percent is not None and percent <= self._low_threshold:
            return self._low_fill
        return self._fill

    def _draw_wave(self, w, h, frac):
        color = self._color_for(self._percent)
        x0, x1, y0, y1 = 1, w - 2, 1, h - 2
        surface = (y1 - y0) * frac
        # 波高不超过液面到轨道上下边缘的距离，避免越界和夸大边界电量。
        max_amp = min(surface, (y1 - y0) - surface)
        base_y = y1 - surface
        for amp, phase, wave_color in (
                (min(h * 0.02, max_amp), self._phase + 2.0, self._border),
                (min(h * 0.01, max_amp), self._phase, color)):
            top = []
            for i in range(SAMPLES):
                x = x0 + (x1 - x0) * i / (SAMPLES - 1)
                y = base_y + amp * math.sin(2 * math.pi * i / (SAMPLES - 1) + phase)
                top.extend((x, y))
            # 沿轮廓顺时针闭合，避免多边形自交。
            self.create_polygon(*(top + [x1, y1, x0, y1]), fill=wave_color,
                                outline="", tags=WAVE_TAG)

    # ----- 动画 -----

    def _advance(self):
        self._anim_id = None
        if self._percent is None or not 0 < self._percent < 100:
            return
        self._phase += PHASE_STEP
        # 只删除并重画带 wave 标签的多边形，避免整块重画闪烁
        self.delete(WAVE_TAG)
        w = self.winfo_width()
        h = self.winfo_height()
        if w > 2 and h > 2:
            self._draw_wave(w, h, self._percent / 100.0)
        self._anim_id = self.after(FRAME_MS, self._advance)
