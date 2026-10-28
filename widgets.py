"""自绘控件与配色：尽量贴近桌面版的深色背景 + 大疆绿风格。

桌面版用 QSS 做的事，这里全部用 canvas 指令 + KV 规则实现。
"""

from kivy.graphics import Color, Ellipse, Line, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput

# ---------------- 桌面版配色 ----------------
BG = [0.133, 0.157, 0.188, 1.0]            # #222830 主背景
PANEL = [0.188, 0.220, 0.259, 1.0]         # #303842 面板/按钮常态
PANEL_HOVER = [0.235, 0.278, 0.329, 1.0]   # #3c4754 悬停
BORDER = [0.267, 0.298, 0.345, 1.0]        # #444c58 描边
INPUT_BG = [0.149, 0.173, 0.204, 1.0]      # #262c34 输入框内凹底色
GREEN = [0.000, 0.784, 0.392, 1.0]         # #00c864 大疆绿
GREEN_DARK = [0.000, 0.600, 0.306, 1.0]    # #00994e 按下
TEXT = [0.933, 0.933, 0.933, 1.0]
TERMINAL_BG = [0.106, 0.125, 0.153, 1.0]   # #1b2027 终端背景
BLACK = [0.067, 0.067, 0.067, 1.0]


class Panel(BoxLayout):
    """带圆角背景和描边的容器。"""

    bg_color = ListProperty(PANEL)
    line_color = ListProperty(BORDER)


class Chip(Label):
    """顶部状态条上的一枚小标签。"""

    border_rgba = ListProperty(BORDER)


class FlatButton(Button):
    """扁平按钮：常态深灰，按下或 active 时变成大疆绿。"""

    normal_color = ListProperty(PANEL_HOVER)
    active_color = ListProperty(GREEN)
    active = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        with self.canvas.before:
            self._bg_color = Color(rgba=self.normal_color)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(4)])
        self.bind(pos=self._sync_rect, size=self._sync_rect,
                  state=self._sync_color, active=self._sync_color)

    def _sync_rect(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _sync_color(self, *_):
        on = self.active or self.state == "down"
        self._bg_color.rgba = self.active_color if on else self.normal_color


class EditField(TextInput):
    """带描边的单行输入框，聚焦时描边变绿。"""

    bg_color = ListProperty(INPUT_BG)
    line_color = ListProperty(BORDER)
    focus_line_color = ListProperty(GREEN)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_active = ""
        self.background_color = (0, 0, 0, 0)
        self.foreground_color = (1, 1, 1, 1)
        self.hint_text_color = (0.55, 0.58, 0.62, 1)
        self.selection_color = (0.0, 0.784, 0.392, 0.4)
        self.cursor_color = GREEN
        self.padding = [dp(6), dp(4)]
        with self.canvas.before:
            self._bg_color = Color(rgba=self.bg_color)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(4)])
            self._ln_color = Color(rgba=self.line_color)
            self._ln = Line(rounded_rectangle=(0, 0, 0, 0, dp(4)), width=1)
        self.bind(pos=self._sync, size=self._sync, focus=self._sync)

    def _sync(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self._ln.rounded_rectangle = (self.x, self.y, self.width, self.height, dp(4))
        self._ln_color.rgba = self.focus_line_color if self.focus else self.line_color


class LogView(EditField):
    """终端日志：只读、可滚动、绿字深底。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", True)
        kwargs.setdefault("readonly", True)
        super().__init__(**kwargs)
        self.multiline = True
        self.readonly = True
        self.bg_color = TERMINAL_BG
        self.foreground_color = list(GREEN)
        self.cursor_color = (0, 0, 0, 0)


class JoystickPad(FloatLayout):
    """摇杆 / 方向键二合一。

    摇杆模式下输出连续的 (-1..1) 归一化值；方向键模式输出 up/down/left/right。
    两种模式都支持触摸拖动，摇杆只跟随第一个按下的手指。
    """

    mode_joystick = BooleanProperty(True)
    dir_name = StringProperty("")
    knob_size = NumericProperty(dp(34))

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._radius = 0.0
        self._kx = 0.0
        self._ky = 0.0
        with self.canvas.before:
            self._ring_color = Color(rgba=BORDER)
            self._ring = Line(circle=(0, 0, 1), width=1.2)
            self._knob_color = Color(rgba=GREEN)
            self._knob = Ellipse(size=(self.knob_size, self.knob_size))

        self._dir_buttons = {}
        for name, text in (("up", "前"), ("down", "后"), ("left", "左"), ("right", "右")):
            btn = FlatButton(text=text, active_color=GREEN_DARK,
                             size_hint=(None, None), size=(dp(46), dp(46)))
            btn.bind(on_press=lambda _w, n=name: self._press_dir(n),
                     on_release=lambda _w: self._release_dir())
            self.add_widget(btn)
            self._dir_buttons[name] = btn

        self.bind(pos=self._sync_geometry, size=self._sync_geometry,
                  mode_joystick=self._sync_mode, knob_size=self._sync_geometry)
        self._sync_mode()

    # ---------- 绘制 ----------
    def _sync_geometry(self, *_):
        cx, cy = self.center
        self._radius = max(0.0, min(self.width, self.height) * 0.5 - dp(6))
        self._ring.circle = (cx, cy, self._radius)
        self._knob.size = (self.knob_size, self.knob_size)
        self._knob.pos = (cx + self._kx - self.knob_size * 0.5,
                          cy + self._ky - self.knob_size * 0.5)
        self._layout_dir_buttons()

    def _sync_mode(self, *_):
        joystick = self.mode_joystick
        self._ring_color.rgba = BORDER if joystick else (0, 0, 0, 0)
        self._knob_color.rgba = GREEN if joystick else (0, 0, 0, 0)
        for btn in self._dir_buttons.values():
            btn.opacity = 0 if joystick else 1
            btn.disabled = joystick
        if joystick:
            self.dir_name = ""
        else:
            self._kx = self._ky = 0.0
        self._sync_geometry()

    def _layout_dir_buttons(self):
        cx, cy = self.center
        size = dp(46)
        gap = dp(6)
        self._dir_buttons["up"].pos = (cx - size * 0.5, cy + gap)
        self._dir_buttons["down"].pos = (cx - size * 0.5, cy - size - gap)
        self._dir_buttons["left"].pos = (cx - size - gap, cy - size - gap)
        self._dir_buttons["right"].pos = (cx + gap, cy - size - gap)

    def reset(self):
        self._kx = self._ky = 0.0
        self.dir_name = ""
        self._sync_geometry()

    # ---------- 取值 ----------
    def get_value(self):
        if self._radius <= 0:
            return 0.0, 0.0
        return (round(self._kx / self._radius, 2),
                round(-self._ky / self._radius, 2))

    # ---------- 触摸 ----------
    def on_touch_down(self, touch):
        if self.mode_joystick:
            if self.collide_point(*touch.pos):
                touch.grab(self)
                self._move_knob(touch.pos)
                return True
            return False
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self.mode_joystick and touch.grab_current is self:
            self._move_knob(touch.pos)
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self._kx = self._ky = 0.0
            self._sync_geometry()
            return True
        return super().on_touch_up(touch)

    def _move_knob(self, pos):
        cx, cy = self.center
        dx, dy = pos[0] - cx, pos[1] - cy
        dist = (dx * dx + dy * dy) ** 0.5
        if dist > self._radius and dist > 0:
            dx = dx * self._radius / dist
            dy = dy * self._radius / dist
        self._kx, self._ky = dx, dy
        self._sync_geometry()

    def _press_dir(self, name):
        self.dir_name = name

    def _release_dir(self):
        self.dir_name = ""


class ControlRoot(BoxLayout):
    """根布局，具体结构见 control.kv 的同名规则。"""
