"""Optional Windows global Ctrl+Shift+R, with its own Windows message thread."""
import ctypes
from ctypes import wintypes
import os
from queue import Queue, Empty
import threading


class GlobalHotkey:
    ID = 0x5043

    def __init__(self):
        self.enabled = False
        self._events = Queue()
        self._stop = threading.Event()
        self._thread = None

    def enable(self):
        if self.enabled:
            return
        if os.name != 'nt':
            raise RuntimeError('Global hotkeys require Windows.')
        self._stop.clear()
        ready = threading.Event()
        def pump():
            u = ctypes.windll.user32
            self.enabled = bool(u.RegisterHotKey(None, self.ID, 0x4000 | 0x0002 | 0x0004, ord('R')))
            ready.set()
            if not self.enabled:
                return
            try:
                msg = wintypes.MSG()
                while not self._stop.wait(0.02):
                    while u.PeekMessageW(ctypes.byref(msg), None, 0x0312, 0x0312, 1):
                        if msg.wParam == self.ID:
                            self._events.put(True)
            finally:
                u.UnregisterHotKey(None, self.ID)
                self.enabled = False
        self._thread = threading.Thread(target=pump, daemon=True)
        self._thread.start()
        if not ready.wait(2):
            self.close()
            raise RuntimeError('Windows did not respond to the hotkey registration.')
        if not self.enabled:
            raise RuntimeError('Ctrl+Shift+R is already in use by another application.')

    def poll(self):
        try:
            return self._events.get_nowait()
        except Empty:
            return False

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        while self.poll():
            pass
