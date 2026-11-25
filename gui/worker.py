# gui/worker.py

import asyncio
import json
import aiohttp
from PySide6.QtCore import QThread, Signal


class WebSocketWorker(QThread):
    status_received = Signal(str)
    token_received = Signal(str)
    done_received = Signal()
    user_transcription_received = Signal(str)
    error_received = Signal(str)
    connected_signal = Signal()
    disconnected_signal = Signal()
    task_update_received = Signal(dict)
    route_update_received = Signal(dict)

    def __init__(self, url="ws://127.0.0.1:8000/ws"):
        super().__init__()
        self.url = url
        self._running = True
        self.send_queue = None
        self.loop = None
        self._stop_event = None

    def send_message(self, message: dict):
        if self.loop and self.loop.is_running() and self.send_queue is not None:
            self.loop.call_soon_threadsafe(self.send_queue.put_nowait, message)

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.send_queue = asyncio.Queue()
        self._stop_event = asyncio.Event()
        try:
            self.loop.run_until_complete(self._connect_and_listen())
        finally:
            pending = asyncio.all_tasks(self.loop)
            for task in pending:
                task.cancel()
            if pending:
                self.loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self.loop.close()

    async def _connect_and_listen(self):
        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.url) as ws:
                        self.connected_signal.emit()

                        async def send_loop():
                            try:
                                while self._running:
                                    msg = await self.send_queue.get()
                                    await ws.send_json(msg)
                                    self.send_queue.task_done()
                            except asyncio.CancelledError:
                                pass

                        send_task = asyncio.create_task(send_loop())

                        async for msg in ws:
                            if not self._running:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                msg_type = data.get("type")

                                if msg_type == "status":
                                    self.status_received.emit(data.get("state", "Idle"))
                                elif msg_type == "token":
                                    self.token_received.emit(data.get("text", ""))
                                elif msg_type == "user_transcription":
                                    self.user_transcription_received.emit(
                                        data.get("text", "")
                                    )
                                elif msg_type == "error":
                                    self.error_received.emit(data.get("message", "Unknown error"))
                                elif msg_type == "done":
                                    self.done_received.emit()
                                elif msg_type == "task_update":
                                    self.task_update_received.emit(data.get("payload") or {})
                                elif msg_type == "route_update":
                                    self.route_update_received.emit(data.get("payload") or {})
                            elif msg.type in (
                                aiohttp.WSMsgType.CLOSED,
                                aiohttp.WSMsgType.ERROR,
                            ):
                                break

                        send_task.cancel()
            except Exception:
                if self._running:
                    self.error_received.emit("Connection lost. Retrying...")

            self.disconnected_signal.emit()
            if self._running:
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    pass

    def stop(self):
        self._running = False
        if self.loop and self.loop.is_running() and self._stop_event is not None:
            self.loop.call_soon_threadsafe(self._stop_event.set)
