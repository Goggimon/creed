# gui/components/global_hotkey.py

import ctypes
import sys
from PySide6.QtCore import QThread, Signal


class MacGlobalHotkey(QThread):
    """Registers system-wide macOS hotkeys (Option+Space and Cmd+Shift+K) via Carbon without Accessibility prompts."""

    triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._callback_ref = None

    def run(self):
        if sys.platform != "darwin":
            return
        try:
            carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
            cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        except Exception:
            return

        class EventTypeSpec(ctypes.Structure):
            _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]

        class EventHotKeyID(ctypes.Structure):
            _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]

        kEventClassKeyboard = 0x6B657962  # 'keyb'
        kEventHotKeyPressed = 5
        cmdKey = 1 << 8
        shiftKey = 1 << 9
        optionKey = 1 << 11

        kVK_Space = 49
        kVK_ANSI_K = 40

        HANDLER_TYPE = ctypes.CFUNCTYPE(
            ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p
        )

        def _on_hotkey(next_handler, event_ref, user_data):
            self.triggered.emit()
            return 0

        self._callback_ref = HANDLER_TYPE(_on_hotkey)

        carbon.GetApplicationEventTarget.restype = ctypes.c_void_p
        target = carbon.GetApplicationEventTarget()

        spec = EventTypeSpec(kEventClassKeyboard, kEventHotKeyPressed)
        handler_ref = ctypes.c_void_p()
        carbon.InstallEventHandler(
            ctypes.c_void_p(target),
            self._callback_ref,
            1,
            ctypes.byref(spec),
            None,
            ctypes.byref(handler_ref),
        )

        sig = 0x43524544  # 'CRED'
        hk1 = ctypes.c_void_p()
        hk2 = ctypes.c_void_p()
        # 1: Option + Space
        carbon.RegisterEventHotKey(
            kVK_Space, optionKey, EventHotKeyID(sig, 1), ctypes.c_void_p(target), 0, ctypes.byref(hk1)
        )
        # 2: Cmd + Shift + K
        carbon.RegisterEventHotKey(
            kVK_ANSI_K, cmdKey | shiftKey, EventHotKeyID(sig, 2), ctypes.c_void_p(target), 0, ctypes.byref(hk2)
        )

        # Poll CFRunLoop briefly so thread exits cleanly on shutdown
        cf.CFRunLoopGetCurrent.restype = ctypes.c_void_p
        cf.CFStringCreateWithCString.restype = ctypes.c_void_p
        mode = cf.CFStringCreateWithCString(None, b"kCFRunLoopDefaultMode", 0x08000100)
        cf.CFRunLoopRunInMode.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_bool]

        while self._running:
            cf.CFRunLoopRunInMode(ctypes.c_void_p(mode), 0.15, False)

        if hk1.value:
            carbon.UnregisterEventHotKey(hk1)
        if hk2.value:
            carbon.UnregisterEventHotKey(hk2)

    def stop(self):
        self._running = False
