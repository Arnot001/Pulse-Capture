import ctypes
from ctypes import wintypes
import tkinter as tk
from capture.region_picker import region_from_points
from capture.window_picker import desktop_bounds
from . import theme as t


class RegionOverlay(tk.Toplevel):
    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.on_select, self.start = on_select, None
        self.bounds = desktop_bounds()
        x, y, w, h = self.bounds
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.attributes('-alpha', 0.38)
        self.geometry(f'{w}x{h}+0+0')
        self.canvas = tk.Canvas(self, bg=t.BG, highlightthickness=0, cursor='crosshair')
        self.canvas.pack(fill='both', expand=True)
        # SetWindowPos avoids Tk's negative-coordinate right-edge interpretation.
        self.update_idletasks()
        u = ctypes.windll.user32
        u.GetParent.argtypes, u.GetParent.restype = [wintypes.HWND], wintypes.HWND
        u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
        u.SetWindowPos(u.GetParent(self.winfo_id()), None, x, y, w, h, 0x0004)
        self.canvas.create_text(40, 40, anchor='nw', fill='white', font=(t.FONT, 20, 'bold'),
                                text='PULSE // CAPTURE   •   Drag to select an area   •   Esc to cancel')
        self.rect = None
        self.canvas.bind('<ButtonPress-1>', self.begin)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.finish)
        self.bind('<Escape>', lambda _: self.close(None))
        self.protocol('WM_DELETE_WINDOW', lambda: self.close(None))
        self.grab_set()
        self.focus_force()

    def point(self, event):
        x, y, w, h = self.bounds
        return (min(max(event.x_root, x), x + w), min(max(event.y_root, y), y + h))

    def begin(self, event):
        self.start = self.point(event)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(0, 0, 0, 0, outline=t.CYAN, width=3, fill='#428699')

    def drag(self, event):
        if self.start:
            x, y, _, _ = self.bounds
            ex, ey = self.point(event)
            self.canvas.coords(self.rect, self.start[0] - x, self.start[1] - y, ex - x, ey - y)

    def finish(self, event):
        if self.start:
            try:
                self.close(region_from_points(self.start, self.point(event)))
            except ValueError:
                self.start = None

    def close(self, region):
        self.grab_release()
        self.destroy()
        self.on_select(region)
