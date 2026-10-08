"""Source-space crop interaction over the actual displayed preview frame."""
import tkinter as tk
from ui import theme as t


class CropPreview(tk.Canvas):
    def __init__(self, parent, on_crop, **kwargs):
        super().__init__(parent, **kwargs)
        self.on_crop = on_crop
        self.media = self.crop = self.photo = None
        self.active = False
        self.enabled = False
        self.source_view = False
        self.drag = None
        self.bind('<Button-1>', self.begin)
        self.bind('<B1-Motion>', self.move)
        self.bind('<ButtonRelease-1>', lambda _: setattr(self, 'drag', None))
        self.bind('<Left>', lambda _: self.nudge(-2, 0))
        self.bind('<Right>', lambda _: self.nudge(2, 0))
        self.bind('<Up>', lambda _: self.nudge(0, -2))
        self.bind('<Down>', lambda _: self.nudge(0, 2))

    def show_frame(self, photo, source_view):
        self.photo, self.source_view = photo, source_view
        self.delete('frame')
        self.create_image(self.winfo_width()/2, self.winfo_height()/2,
                          image=photo, tags='frame')
        self.draw_overlay()

    def bounds(self):
        if not self.photo or not self.media:
            return None
        w, h = self.photo.width(), self.photo.height()
        return (self.winfo_width()-w)/2, (self.winfo_height()-h)/2, w, h

    def crop_bounds(self):
        left, top, w, h = self.bounds()
        c = self.crop
        return (left+c.x*w/self.media.width, top+c.y*h/self.media.height,
                left+(c.x+c.width)*w/self.media.width,
                top+(c.y+c.height)*h/self.media.height)

    def draw_overlay(self):
        self.delete('crop')
        self.configure(cursor='fleur' if self.active and self.crop and self.enabled else '')
        if not self.active or not self.source_view or not self.crop or not self.bounds():
            return
        left, top, w, h = self.bounds()
        x1, y1, x2, y2 = self.crop_bounds()
        for rect in ((left, top, left+w, y1), (left, y2, left+w, top+h),
                     (left, y1, x1, y2), (x2, y1, left+w, y2)):
            self.create_rectangle(*rect, fill='#060a10', stipple='gray50', outline='', tags='crop')
        self.create_rectangle(x1, y1, x2, y2, outline=t.CYAN, width=3, tags='crop')
        for fraction in (1/3, 2/3):
            x, y = x1+(x2-x1)*fraction, y1+(y2-y1)*fraction
            self.create_line(x, y1, x, y2, fill=t.TEXT, dash=(3, 5), tags='crop')
            self.create_line(x1, y, x2, y, fill=t.TEXT, dash=(3, 5), tags='crop')

    def begin(self, event):
        if not (self.enabled and self.active and self.source_view and self.crop and self.bounds()):
            return
        x1, y1, x2, y2 = self.crop_bounds()
        if x1 <= event.x <= x2 and y1 <= event.y <= y2:
            self.focus_set()
            self.drag = (event.x, event.y, self.crop)

    def move(self, event):
        if not self.drag or not self.enabled or not self.active or not self.source_view:
            return
        x, y, crop = self.drag
        _, _, w, h = self.bounds()
        self.on_crop(crop.moved(self.media, crop.x+(event.x-x)*self.media.width/w,
                               crop.y+(event.y-y)*self.media.height/h))

    def nudge(self, dx, dy):
        if self.enabled and self.active and self.source_view and self.crop:
            self.on_crop(self.crop.moved(self.media, self.crop.x+dx, self.crop.y+dy))
        return 'break'
