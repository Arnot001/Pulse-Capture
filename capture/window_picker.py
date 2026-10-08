"""Windows discovery and DPI helpers. Handles are pointer-sized on 64-bit Windows."""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os


def user32():
    if os.name != 'nt':
        raise RuntimeError('Window capture is only supported on Windows.')
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.IsWindow.argtypes = [wintypes.HWND]
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsIconic.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    return u


def enable_dpi_awareness():
    if os.name == 'nt':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (OSError, AttributeError):
            ctypes.windll.user32.SetProcessDPIAware()


def desktop_bounds():
    u = user32()
    return tuple(u.GetSystemMetrics(i) for i in (76, 77, 78, 79))


@dataclass(frozen=True)
class Window:
    hwnd: int
    title: str
    minimized: bool = False


def list_windows():
    u = user32()
    windows = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    u.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]

    @callback_type
    def visit(hwnd, _):
        process_id = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if u.IsWindowVisible(hwnd) and process_id.value != os.getpid():
            class_name = ctypes.create_unicode_buffer(256)
            u.GetClassNameW(hwnd, class_name, len(class_name))
            if class_name.value in ('Progman', 'WorkerW'):
                return True
            length = u.GetWindowTextLengthW(hwnd)
            if length:
                title = ctypes.create_unicode_buffer(length + 1)
                u.GetWindowTextW(hwnd, title, length + 1)
                windows.append(Window(int(hwnd), title.value, bool(u.IsIconic(hwnd))))
        return True

    u.EnumWindows(visit, 0)
    return sorted(windows, key=lambda w: w.title.casefold())


def validate_window(hwnd):
    u = user32()
    if not u.IsWindow(hwnd) or not u.IsWindowVisible(hwnd):
        raise ValueError('The selected window is no longer available. Select it again.')
    if u.IsIconic(hwnd):
        raise ValueError('Restore the selected window before recording.')
