"""A small trim range with draggable handles and a separate playhead."""
import tkinter as tk
from ui import theme as t
from .models import TrimRange, format_time


class Timeline(tk.Canvas):
    def __init__(self, parent, on_seek, on_trim):
        super().__init__(parent, height=65, bg=t.BG, highlightthickness=0, cursor='hand2')
        self.on_seek, self.on_trim = on_seek, on_trim
        self.media = self.trim = None
        self.position = 0
        self.enabled = True
        self.drag = None
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<Button-1>', self.begin)
        self.bind('<B1-Motion>', self.move)
        self.bind('<ButtonRelease-1>', lambda _: setattr(self, 'drag', None))

    def x(self, seconds):
        return 14 + seconds / self.media.duration * max(1, self.winfo_width() - 28)

    def seconds(self, x):
        return max(0, min(self.media.duration, (x - 14) / max(1, self.winfo_width() - 28) * self.media.duration))

    def draw(self):
        self.delete('all')
        if not self.media:
            return
        right = self.winfo_width() - 14
        self.create_rectangle(14, 12, right, 36, fill=t.CONTROL, outline='')
        start, end = self.x(self.trim.start), self.x(self.trim.end)
        self.create_rectangle(start, 12, end, 36, fill='#17464f', outline=t.CYAN)
        for point in (start, end):
            self.create_rectangle(point-5, 8, point+5, 40, fill=t.CYAN, outline='')
            self.create_line(point, 18, point, 30, fill=t.BG, width=2)
        point = self.x(self.position)
        self.create_line(point, 5, point, 43, fill=t.TEXT, width=2)
        self.create_polygon(point-5, 2, point+5, 2, point, 8, fill=t.TEXT)
        self.create_text(14, 55, text='0:00', anchor='w', fill=t.MUTED, font=(t.MONO, -11))
        self.create_text(right, 55, text=format_time(self.media.duration), anchor='e', fill=t.MUTED, font=(t.MONO, -11))

    def begin(self, event):
        if not self.media or not self.enabled:
            return
        distances = {'start': abs(event.x-self.x(self.trim.start)), 'end': abs(event.x-self.x(self.trim.end))}
        nearest = min(distances, key=distances.get)
        self.drag = nearest if distances[nearest] <= 13 else 'seek'
        self.move(event)

    def move(self, event):
        if not self.drag or not self.enabled:
            return
        value = self.seconds(event.x)
        gap = min(1 / self.media.fps, self.media.duration)
        if self.drag == 'start':
            self.on_trim(TrimRange(min(value, self.trim.end-gap), self.trim.end), 'start')
        elif self.drag == 'end':
            self.on_trim(TrimRange(self.trim.start, max(value, self.trim.start+gap)), 'end')
        else:
            self.on_seek(value)
