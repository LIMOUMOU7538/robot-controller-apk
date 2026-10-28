"""网络层：WebSocket 指令客户端 + UDP 视频接收。

协议与桌面版完全一致：
    驱动轮  ws://IP:8765   <- "vx,vy"
    机械臂  ws://IP:8766   <- "arm,<硬件通道>,<角度>"
    摄像头  udp://:8080     -> JPEG 图像帧
"""

import asyncio
import socket
import threading

try:
    # websockets >= 14 的新 asyncio 实现
    from websockets.asyncio.client import connect as ws_connect
except ImportError:  # websockets <= 13
    from websockets import connect as ws_connect


class WsClientThread(threading.Thread):
    """后台线程里跑一个 asyncio 事件循环，长期保持 WebSocket 连接。

    主线程只用 send() / stop()，其他状态全部通过 dispatch 回调回主线程，
    所以不依赖 Kivy 的线程模型。
    """

    def __init__(self, host, port, name, dispatch, on_log=None,
                 on_connected=None, on_closed=None):
        super().__init__(daemon=True)
        self.host = host
        self.port = int(port)
        self.name = name
        self._dispatch = dispatch
        self._on_log = on_log
        self._on_connected = on_connected
        self._on_closed = on_closed
        self._lock = threading.Lock()
        self._loop = None
        self._queue = None
        self._stop_event = None
        self._connected = False

    # ---------- 主线程调用 ----------
    def send(self, msg):
        with self._lock:
            loop, queue = self._loop, self._queue
        if loop is None or queue is None or not self._connected:
            return
        try:
            loop.call_soon_threadsafe(self._put, msg)
        except RuntimeError:
            pass  # 循环已关闭

    def stop(self):
        with self._lock:
            loop, stop_event = self._loop, self._stop_event
        if loop is not None and stop_event is not None:
            try:
                loop.call_soon_threadsafe(stop_event.set)
            except RuntimeError:
                pass

    def is_connected(self):
        return self._connected

    # ---------- 线程内 ----------
    def _put(self, msg):
        queue = self._queue
        if queue is None:
            return
        try:
            queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass  # 网络慢时丢掉旧指令，不让队列堆积

    def _log(self, text):
        if self._on_log:
            self._dispatch(self._on_log, text)

    def _set_connected(self, ok):
        self._connected = ok
        if self._on_connected:
            self._dispatch(self._on_connected, ok)

    def run(self):
        try:
            asyncio.run(self._main())
        except Exception as exc:  # noqa: BLE001 线程内兜底
            self._log("[%s] 线程异常: %s" % (self.name, exc))
        finally:
            if self._on_closed:
                self._dispatch(self._on_closed, self)

    async def _main(self):
        uri = "ws://%s:%d" % (self.host, self.port)
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=32)
        stop_event = asyncio.Event()
        with self._lock:
            self._loop, self._queue, self._stop_event = loop, queue, stop_event

        try:
            async with ws_connect(uri, ping_interval=20, open_timeout=5) as ws:
                self._set_connected(True)
                self._log("[%s] 已连接 %s" % (self.name, uri))
                tasks = [
                    asyncio.create_task(self._recv_loop(ws)),
                    asyncio.create_task(self._send_loop(ws)),
                    asyncio.create_task(stop_event.wait()),
                ]
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in tasks:
                    task.cancel()
        except Exception as exc:  # noqa: BLE001 连接失败/中断都走这里
            self._log("[%s] 连接失败: %s" % (self.name, exc))
        finally:
            self._set_connected(False)
            with self._lock:
                self._loop = self._queue = self._stop_event = None

    async def _recv_loop(self, ws):
        try:
            async for _ in ws:
                pass
        except Exception:  # noqa: BLE001
            pass

    async def _send_loop(self, ws):
        while True:
            msg = await self._queue.get()
            try:
                await ws.send(msg)
            except Exception:  # noqa: BLE001
                return


class UdpImageReceiver(threading.Thread):
    """绑定 UDP 端口收 JPEG 帧。

    线程只保存最新一帧原始字节，解码 + 上纹理交给主线程的定时器做，
    这样 30fps 下不会出现解码任务堆积。
    """

    def __init__(self, port, dispatch, on_log=None):
        super().__init__(daemon=True)
        self.port = int(port)
        self._dispatch = dispatch
        self._on_log = on_log
        self._sock = None
        self._running = False
        self._lock = threading.Lock()
        self._data = None
        self._seq = 0

    def latest(self):
        """返回 (序号, 原始字节)。序号变化说明是新的一帧。"""
        with self._lock:
            return self._seq, self._data

    def stop(self):
        self._running = False
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _log(self, text):
        if self._on_log:
            self._dispatch(self._on_log, text)

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(0.4)
        try:
            sock.bind(("0.0.0.0", self.port))
        except OSError as exc:
            self._log("[摄像头] UDP 绑定 %d 失败: %s" % (self.port, exc))
            return

        self._sock = sock
        self._running = True
        self._log("[摄像头] 开始监听 UDP %d" % self.port)

        while self._running:
            try:
                data, _addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data:
                continue
            with self._lock:
                self._data = data
                self._seq += 1

        try:
            sock.close()
        except OSError:
            pass
        self._log("[摄像头] 已停止监听 UDP %d" % self.port)
