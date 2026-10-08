"""Privacy drawing on the rendered result, mapped back to source pixels."""
from .crop_preview import CropPreview
from .privacy import source_viewport, rectangle_from_points
from ui import theme as t


class PrivacyPreview(CropPreview):
    def __init__(self, parent, on_crop, on_privacy, on_zoom=None, **kwargs):
        super().__init__(parent, on_crop, **kwargs)
        self.on_privacy = on_privacy
        self.on_zoom = on_zoom
        self.privacy_active = False
        self.zoom_active = False
        self.zoom_focus = (0.5, 0.5)
        self.zoom_drag = False
        self.mask = None
        self.mode = 'Blur'
        self.display_crop = None
        self.gesture = self.candidate = None
        self.bind('<ButtonRelease-1>', self.finish)

    def show_frame(self, photo, source_view, edits=None):
        self.display_crop = edits.crop if edits else None
        super().show_frame(photo, source_view)

    def ready(self):
        return (self.privacy_active and self.enabled and not self.source_view and
                self.photo and self.media and self.display_crop == self.crop)

    def viewport(self):
        return source_viewport(self.media, self.crop)

    def dimensions(self):
        v = self.viewport()
        return (v.width+1)//2*2, (v.height+1)//2*2

    def source_point(self, x, y):
        left, top, w, h = self.bounds()
        width, height = self.dimensions()
        v = self.viewport()
        return (max(v.x, min(v.right, v.x+(x-left)*width/w)),
                max(v.y, min(v.bottom, v.y+(y-top)*height/h)))

    def screen_rect(self, rect):
        left, top, w, h = self.bounds()
        width, height = self.dimensions()
        v = self.viewport()
        return (left+(rect.x-v.x)*w/width, top+(rect.y-v.y)*h/height,
                left+(rect.right-v.x)*w/width, top+(rect.bottom-v.y)*h/height)

    def visible_mask(self):
        return self.mask.intersect(self.viewport()) if self.mask else None

    def zoom_ready(self):
        return (self.zoom_active and self.enabled and not self.source_view and
                self.photo and self.media and self.display_crop == self.crop)

    def zoom_screen_point(self):
        if not self.zoom_ready():
            return None
        source_x = self.zoom_focus[0] * self.media.width
        source_y = self.zoom_focus[1] * self.media.height
        v = self.viewport()
        source_x = max(v.x, min(v.right, source_x))
        source_y = max(v.y, min(v.bottom, source_y))
        return self.screen_rect(type(v)(round(source_x), round(source_y), 1, 1))[:2]

    def _set_zoom_focus(self, event):
        if not self.zoom_ready() or not self.on_zoom:
            return
        x, y = self.source_point(event.x, event.y)
        self.zoom_focus = (max(0.0, min(1.0, x / self.media.width)),
                           max(0.0, min(1.0, y / self.media.height)))
        self.on_zoom(*self.zoom_focus)
        self.draw_overlay()

    def draw_overlay(self):
        super().draw_overlay()
        self.delete('privacy')
        if not self.ready():
            return
        self.configure(cursor='crosshair')
        rect = self.candidate or self.visible_mask()
        if rect is None:
            return
        x1, y1, x2, y2 = self.screen_rect(rect)
        self.create_rectangle(x1, y1, x2, y2, outline=t.CYAN, width=2, tags='privacy')
        for x, y in ((x1, y1), (x2, y1), (x1, y2), (x2, y2)):
            self.create_rectangle(x-4, y-4, x+4, y+4, fill=t.CYAN, outline=t.BG, tags='privacy')
        self.create_text(x1+7, y1+7, text=self.mode.upper(), anchor='nw', fill=t.CYAN,
                         font=(t.FONT, -11, 'bold'), tags='privacy')
        if self.zoom_ready():
            point = self.zoom_screen_point()
            if point:
                x, y = point
                radius = 14
                self.create_oval(x-radius, y-radius, x+radius, y+radius,
                                 outline=t.CYAN, width=2, tags='zoom')
                self.create_line(x-radius-7, y, x+radius+7, y, fill=t.CYAN, width=2, tags='zoom')
                self.create_line(x, y-radius-7, x, y+radius+7, fill=t.CYAN, width=2, tags='zoom')

    def begin(self, event):
        if self.zoom_active:
            if self.zoom_ready():
                self.focus_set()
                self.zoom_drag = True
                self._set_zoom_focus(event)
            return
        if not self.privacy_active:
            return super().begin(event)
        if not self.ready():
            return
        left, top, w, h = self.bounds()
        if not (left <= event.x <= left+w and top <= event.y <= top+h):
            return
        self.focus_set()
        point = self.source_point(event.x, event.y)
        rect = self.visible_mask()
        if rect:
            x1, y1, x2, y2 = self.screen_rect(rect)
            corners = [(x1, y1, rect.right, rect.bottom), (x2, y1, rect.x, rect.bottom),
                       (x1, y2, rect.right, rect.y), (x2, y2, rect.x, rect.y)]
            for x, y, opposite_x, opposite_y in corners:
                if abs(event.x-x) <= 9 and abs(event.y-y) <= 9:
                    self.gesture = ('resize', (opposite_x, opposite_y), rect)
                    self.candidate = rect
                    return
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self.gesture = ('move', point, rect)
                self.candidate = rect
                return
        self.gesture = ('draw', point, None)
        self.candidate = None

    def move(self, event):
        if self.zoom_active:
            if self.zoom_drag:
                self._set_zoom_focus(event)
            return
        if not self.privacy_active:
            return super().move(event)
        if not self.ready() or not self.gesture:
            return
        mode, anchor, rect = self.gesture
        x, y = self.source_point(event.x, event.y)
        if mode == 'move':
            self.candidate = rect.moved(self.viewport(), rect.x+x-anchor[0], rect.y+y-anchor[1])
        else:
            candidate = rectangle_from_points(self.viewport(), *anchor, x, y)
            if candidate:
                self.candidate = candidate
        self.draw_overlay()

    def finish(self, _=None):
        self.drag = None
        self.zoom_drag = False
        if (self.gesture and self.candidate and self.ready() and
                self.candidate.width >= 2 and self.candidate.height >= 2):
            self.on_privacy(self.candidate)
        self.gesture = self.candidate = None
        self.draw_overlay()

    def nudge(self, dx, dy):
        if not self.privacy_active:
            return super().nudge(dx, dy)
        if self.ready() and self.visible_mask():
            rect = self.mask
            self.on_privacy(rect.moved(self.viewport(), rect.x+dx, rect.y+dy))
        return 'break'
