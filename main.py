"""履带小车 + 机械臂 手机端上位机（Kivy，横屏，复刻桌面版布局）。

协议与桌面版 PySide6 版本完全一致：
    驱动轮  ws://IP:8765   <- "vx,vy"               25Hz
    机械臂  ws://IP:8766   <- "arm,<硬件通道>,<角度>"
    摄像头  udp://:8080     -> JPEG 图像帧

桌面调试：python main.py
安卓打包：buildozer -v android debug
"""

import os
from collections import deque
from io import BytesIO

from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.properties import StringProperty
from kivy.utils import platform

import net
from widgets import (BORDER, GREEN, TEXT, ControlRoot)  # noqa: F401 (ControlRoot 供 KV 使用)

SPEED_MAP = {"慢": 0.3, "中": 0.6, "快": 0.9}
DIR_MAP = {
    "up": (0.0, 0.6),
    "down": (0.0, -0.6),
    "left": (0.6, 0.0),
    "right": (-0.6, 0.0),
    "": (0.0, 0.0),
}
ARM_NAMES = ("夹子", "夹子旋转", "中臂", "大臂")
UI_TO_HW_CH = (3, 2, 1, 0)
CHANNEL_TAGS = ("驱动轮", "机械臂", "摄像头")

# 安卓 / 桌面上的中文字体，避免中文显示成方块
CJK_CANDIDATES = (
    "/system/fonts/NotoSansCJK-Regular.ttc",
    "/system/fonts/NotoSansCJKsc-Regular.otf",
    "/system/fonts/NotoSansSC-Regular.otf",
    "/system/fonts/DroidSansFallback.ttf",
    "/system/fonts/DroidSansFallbackFull.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "/System/Library/Fonts/PingFang.ttc",
)


def register_cjk_font():
    for path in CJK_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            LabelBase.register(name="CJK", fn_regular=path)
            return "CJK"
        except Exception:  # noqa: BLE001 字体损坏就继续找下一个
            continue
    return "Roboto"


def guess_ext(data):
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    return "jpg"


class ControlApp(App):
    cjk_font = StringProperty("Roboto")

    # ---------- 生命周期 ----------
    def build(self):
        self.cjk_font = register_cjk_font()
        self.conn = [False, False, False]      # 0驱动轮 1机械臂 2摄像头
        self.speed_wheel_scale = 0.6
        self.arm_step_scale = 0.6
        self.arm_angle = [90, 90, 90, 90]
        self.ws_wheel = None
        self.ws_arm = None
        self.udp = None
        self._last_seq = 0
        self._cam_frames = 0
        self._last_wheel_log = (0.0, 0.0)
        self._long_event = None
        self._ev_control = None
        self._ev_render = None
        self._ev_stat = None
        self._log_lines = deque(maxlen=400)
        return ControlRoot()

    def on_start(self):
        if platform not in ("android", "ios"):
            Window.size = (1180, 620)
        self.set_speed("wheel", "中")
        self.set_speed("arm", "中")
        self._ev_control = Clock.schedule_interval(self.on_control_tick, 0.04)
        self._ev_render = Clock.schedule_interval(self.on_render_tick, 0.033)
        self._ev_stat = Clock.schedule_interval(self.on_stat_tick, 1.0)

    def on_stop(self):
        for event in (self._ev_control, self._ev_render, self._ev_stat, self._long_event):
            if event is not None:
                event.cancel()
        for client in (self.ws_wheel, self.ws_arm):
            if client is not None:
                client.stop()
        if self.udp is not None:
            self.udp.stop()

    # ---------- 线程 -> 主线程 ----------
    # 注意：不能叫 dispatch，会和 EventDispatcher.dispatch 冲突
    def ui_call(self, func, *args):
        Clock.schedule_once(lambda _dt: func(*args), 0)

    def log(self, text):
        self._log_lines.append(text)
        view = self.root.ids.terminal
        view.text = "\n".join(self._log_lines)
        Clock.schedule_once(lambda _dt: setattr(view, "scroll_y", 0), 0)

    # ---------- 连接管理 ----------
    def set_conn(self, idx, ok):
        self.conn[idx] = ok
        chip = self.root.ids[("chip_wheel", "chip_arm", "chip_cam")[idx]]
        name = CHANNEL_TAGS[idx]
        if ok:
            ip = ""
            if idx < 2:
                ip = self.root.ids[("ip_wheel", "ip_arm")[idx]].text.strip()
            chip.text = "%s %s" % (name, ip) if ip else "%s 已连接" % name
            chip.color = GREEN
            chip.border_rgba = GREEN
        else:
            chip.text = "%s 【未连接】" % name
            chip.color = TEXT
            chip.border_rgba = BORDER
        self.refresh_status()

    def refresh_status(self):
        marks = ["√" if flag else "×" for flag in self.conn]
        self.root.ids.status_conn.text = (
            "连接：驱动轮%s 机械臂%s 摄像头%s" % tuple(marks))

    def connect_channel(self, idx):
        key = ("wheel", "arm", "cam")[idx]
        ip = self.root.ids["ip_%s" % key].text.strip()
        port_text = self.root.ids["port_%s" % key].text.strip()
        try:
            port = int(port_text)
        except ValueError:
            self.log("端口必须为数字！")
            return

        if idx == 2:
            self._start_camera(port)
            return

        if not ip:
            self.log("IP 不能为空！")
            return

        client = self.ws_wheel if idx == 0 else self.ws_arm
        if client is not None and client.is_alive():
            self.log("%s线程已经在运行，请先断开！" % CHANNEL_TAGS[idx])
            return

        client = net.WsClientThread(
            ip, port, CHANNEL_TAGS[idx], self.ui_call,
            on_log=self.log,
            on_connected=lambda ok, i=idx: self.set_conn(i, ok),
            on_closed=lambda c, i=idx: self._client_closed(i, c),
        )
        if idx == 0:
            self.ws_wheel = client
        else:
            self.ws_arm = client
        self.log("正在连接%s %s:%d" % (CHANNEL_TAGS[idx], ip, port))
        client.start()

    def _client_closed(self, idx, client):
        if idx == 0 and self.ws_wheel is client:
            self.ws_wheel = None
        elif idx == 1 and self.ws_arm is client:
            self.ws_arm = None

    def disconnect_channel(self, idx):
        if not self.conn[idx]:
            return
        if idx == 2:
            self._stop_camera()
            self.set_conn(2, False)
            self.log("摄像头断开连接")
            return
        client = self.ws_wheel if idx == 0 else self.ws_arm
        if client is not None:
            client.stop()
        self.set_conn(idx, False)
        self.log("%s断开连接" % CHANNEL_TAGS[idx])

    # ---------- 摄像头 ----------
    def _start_camera(self, port):
        self._stop_camera()
        self.udp = net.UdpImageReceiver(port, self.ui_call, self.log)
        self.udp.start()
        self._last_seq = 0
        self.set_conn(2, True)

    def _stop_camera(self):
        if self.udp is not None:
            self.udp.stop()
            self.udp = None
        try:
            self.root.ids.cam_view.texture = None
        except Exception:  # noqa: BLE001 部分 Kivy 版本不允许直接置空
            pass

    def on_render_tick(self, _dt):
        receiver = self.udp
        if receiver is None:
            return
        seq, data = receiver.latest()
        if data is None or seq == self._last_seq:
            return
        self._last_seq = seq
        try:
            core = CoreImage(BytesIO(data), ext=guess_ext(data), nocache=True)
        except Exception:  # noqa: BLE001 坏帧直接丢弃
            return
        if core.texture is None:
            return
        self.root.ids.cam_view.texture = core.texture
        self._cam_frames += 1

    # ---------- 驱动轮 ----------
    def on_control_tick(self, _dt):
        pad = self.root.ids.pad
        if pad.mode_joystick:
            vx, vy = pad.get_value()
        else:
            vx, vy = DIR_MAP.get(pad.dir_name, (0.0, 0.0))
        vx *= self.speed_wheel_scale
        vy *= self.speed_wheel_scale

        if self.ws_wheel is None or not self.conn[0]:
            return
        self.ws_wheel.send("%.2f,%.2f" % (vx, vy))
        if abs(vx) > 0.01 or abs(vy) > 0.01:
            current = (round(vx, 2), round(vy, 2))
            if current != self._last_wheel_log:
                self._last_wheel_log = current
                self.log("驱动轮 vx=%.2f, vy=%.2f" % (vx, vy))
        else:
            self._last_wheel_log = (0.0, 0.0)

    # ---------- 机械臂 ----------
    def start_arm_press(self, ui_ch, delta):
        self.stop_arm_press()
        self._arm_step(ui_ch, delta)
        self._long_event = Clock.schedule_interval(
            lambda _dt: self._arm_step(ui_ch, delta), 0.08)

    def stop_arm_press(self):
        if self._long_event is not None:
            self._long_event.cancel()
            self._long_event = None

    def _arm_step(self, ui_ch, delta):
        step = int(round(delta * self.arm_step_scale))
        if step == 0:
            step = 1 if delta > 0 else -1
        angle = max(0, min(180, self.arm_angle[ui_ch] + step))
        self.arm_angle[ui_ch] = angle
        hw_ch = UI_TO_HW_CH[ui_ch]
        if self.ws_arm is not None and self.conn[1]:
            self.ws_arm.send("arm,%d,%d" % (hw_ch, angle))
        self.log("机械臂【%s】通道%d 角度=%d" % (ARM_NAMES[ui_ch], hw_ch, angle))

    # ---------- 交互 ----------
    def set_speed(self, group, text):
        prefix = "spd_w" if group == "wheel" else "spd_a"
        for index in range(3):
            self.root.ids["%s%d" % (prefix, index)].active = (
                self.root.ids["%s%d" % (prefix, index)].text == text)
        value = SPEED_MAP[text]
        if group == "wheel":
            self.speed_wheel_scale = value
            self.log("驱动轮速度切换为：%s" % text)
        else:
            self.arm_step_scale = value
            self.log("机械臂速度切换为：%s" % text)

    def toggle_mode(self):
        pad = self.root.ids.pad
        pad.mode_joystick = not pad.mode_joystick
        pad.reset()
        tip = "摇杆" if pad.mode_joystick else "方向按键"
        self.root.ids.status_mode.text = "模式：%s" % tip
        self.log("【模式切换】%s" % tip)

    # ---------- 状态刷新 ----------
    def on_stat_tick(self, _dt):
        label = self.root.ids.status_fps
        if self.conn[2]:
            label.text = "画面帧率：%d FPS" % self._cam_frames
        else:
            label.text = "收到帧计数：%d" % self._cam_frames
        self._cam_frames = 0
        self.refresh_status()


if __name__ == "__main__":
    ControlApp().run()
