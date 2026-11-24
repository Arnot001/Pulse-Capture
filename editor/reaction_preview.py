"""Small direct-manipulation layer over the existing Quick Edit canvas."""
from dataclasses import replace
import math

from .privacy_preview import PrivacyPreview
from .reaction_geometry import clamp, positioned, visual_bounds
from .reaction_library import ReactionLibrary
from .imported_media import media_bounds, with_media_position
from ui import theme as t


class ReactionPreview(PrivacyPreview):
    def __init__(self, parent, on_crop, on_privacy, on_zoom=None, *, window, **kwargs):
        self.window = window
        self.selected_visual = None
        self.visual_drag = None
        self.render_context = None
        self.asset_metadata = {}
        self.selected_media_index = None
        self.media_drag = None
        super().__init__(parent, on_crop, on_privacy, on_zoom, **kwargs)
        self.bind('<Escape>', self.cancel_visual_drag)

    def context(self):
        w = self.window
        return (w.position, w.trim, w.cuts, replace(w.edits, overlays=()))

    def show_frame(self, photo, source_view, edits=None, position=0):
        w = self.window
        self.render_context = (position, w.trim, w.cuts, replace(edits, overlays=())) if edits else None
        super().show_frame(photo, source_view, edits, position)

    def visual_ready(self):
        w = self.window
        return (self.enabled and self.photo and not self.source_view and w.media and w.trim
                and not w.playing and not w.closing and not w.exporter.busy
                and w.tool.get() not in ('CROP', 'PRIVACY', 'MOTION')
                and self.render_context == self.context())

    def output_time(self):
        w = self.window
        return w.cuts.source_elapsed(w.position, w.trim)/w.edits.speed

    def item(self, cue):
        key = (cue.kind, cue.asset_id)
        if key not in self.asset_metadata:
            self.asset_metadata[key] = ReactionLibrary().metadata(cue.asset_id, cue.kind)
        return self.asset_metadata[key]

    def geometry(self, cue):
        width, height = self.window.edits.encoded_size(self.media)
        return visual_bounds(cue, width, height, self.output_time(), self.item(cue), self.window.edits.bands(self.media))

    def visual_rect(self, cue):
        box = self.geometry(cue)
        if box is None:
            return None
        left, top, w, h = self.bounds()
        width, height = self.window.edits.encoded_size(self.media)
        return (left+box.x*w/width, top+box.y*h/height,
                left+(box.x+box.side)*w/width, top+(box.y+box.side)*h/height)

    def output_point(self, x, y):
        left, top, w, h = self.bounds()
        width, height = self.window.edits.encoded_size(self.media)
        return (x-left)*width/w, (y-top)*height/h

    def visual_index(self):
        return next((i for i, cue in enumerate(self.window.edits.overlays)
                     if cue is self.selected_visual), None)

    def sync_dialogs(self):
        index = self.visual_index()
        if index is not None:
            for dialog in tuple(self.window.auto_children):
                if not dialog.closed and hasattr(dialog, 'sync_from_canvas'):
                    dialog.sync_from_canvas(index, self.selected_visual)

    def select_visual(self, index):
        self.visual_drag = None
        cues = self.window.edits.overlays
        self.selected_visual = cues[index] if index is not None and 0 <= index < len(cues) else None
        self.sync_dialogs()
        self.draw_overlay()


    def media_ready(self):
        w = self.window
        if not (self.enabled and self.photo and not self.source_view and w.media and w.trim
                and not w.playing and not w.closing and not w.exporter.busy
                and w.tool.get() not in ('CROP', 'PRIVACY', 'MOTION') and self.render_context):
            return False
        actual = self.render_context
        current = self.context()
        # Media clips change on every mouse move. Keep the selection guide live
        # while FFmpeg is rendering the next preview frame in the background.
        return (actual[:3] == current[:3]
                and replace(actual[3], media_clips=()) == replace(current[3], media_clips=()))

    def media_rect(self, cue):
        viewport = self.bounds()
        if viewport is None:
            return None
        left, top, w, h = viewport
        width, height = self.window.edits.encoded_size(self.media)
        box = media_bounds(cue, width, height)
        return (left + box.x*w/width, top + box.y*h/height,
                left + (box.x+box.width)*w/width,
                top + (box.y+box.height)*h/height)

    def select_media(self, index, notify=True):
        self.media_drag = None
        cues = self.window.edits.media_clips
        self.selected_media_index = index if index is not None and 0 <= index < len(cues) else None
        if self.selected_media_index is not None:
            self.selected_visual = None
        if notify:
            dialog = self.window.media_dialog
            if dialog is not None and not dialog.closed:
                dialog.sync_from_canvas(self.selected_media_index)
        self.draw_overlay()

    def draw_media_guide(self):
        self.delete('media-guide')
        i = self.selected_media_index
        if not self.media_ready() or i is None or not 0 <= i < len(self.window.edits.media_clips):
            return
        cue = self.window.edits.media_clips[i]
        if not cue.start <= self.output_time() < cue.end:
            return
        rect = self.media_rect(cue)
        if rect is None:
            return
        self.create_rectangle(*rect, outline=t.CYAN, width=2, tags='media-guide')
        for name, x, y in self.media_handles(rect):
            self.create_rectangle(x-5, y-5, x+5, y+5, fill=t.CYAN, outline=t.BG,
                                  tags='media-guide')
        self.create_text(rect[0]+5, max(10,rect[1]-9), text=cue.title[:35],
                         anchor='w', fill=t.CYAN, font=(t.FONT,-9,'bold'), tags='media-guide')
        self.tag_raise('media-guide')

    @staticmethod
    def media_handles(rect):
        x1, y1, x2, y2 = rect
        return [('nw', x1, y1), ('ne', x2, y1), ('sw', x1, y2), ('se', x2, y2)]

    def begin_media(self, event):
        if not self.media_ready():
            return False
        index = self.selected_media_index
        mode = None
        if index is not None and 0 <= index < len(self.window.edits.media_clips):
            cue = self.window.edits.media_clips[index]
            if cue.start <= self.output_time() < cue.end:
                rect = self.media_rect(cue)
                if rect:
                    mode = next((name for name, x, y in self.media_handles(rect)
                                 if abs(event.x-x) <= 9 and abs(event.y-y) <= 9), None)
        if mode is None:
            index = None
            for i in reversed(range(len(self.window.edits.media_clips))):
                cue = self.window.edits.media_clips[i]
                if not cue.start <= self.output_time() < cue.end:
                    continue
                rect = self.media_rect(cue)
                if rect and rect[0] <= event.x <= rect[2] and rect[1] <= event.y <= rect[3]:
                    index = i
                    break
            if index is None:
                self.select_media(None)
                return False
            self.select_media(index)
            mode = 'move'
        cue = self.window.edits.media_clips[index]
        self.focus_set()
        self.media_drag = dict(mode=mode, original=cue,
                               box=media_bounds(cue, *self.window.edits.encoded_size(self.media)),
                               point=self.output_point(event.x, event.y),
                               context=self.context()[:3], viewport=self.bounds(),
                               expected=self.window.edits.media_clips, index=index)
        self.window.note.configure(
            text='Drag media to move · corner handles resize with aspect ratio locked · Esc cancels.',
            fg=t.CYAN)
        return True

    def apply_media(self, cue):
        gesture = self.media_drag
        index = gesture['index'] if gesture is not None else self.selected_media_index
        w = self.window
        if index is None or not 0 <= index < len(w.edits.media_clips):
            return
        total = w.edits.output_duration(w.cuts.kept_duration(w.trim))
        cue.validate(total)
        cues = list(w.edits.media_clips)
        if cues[index] == cue:
            return
        cues[index] = cue
        w.edits = replace(w.edits, media_clips=tuple(cues))
        w.timeline_history = None
        if gesture is not None:
            gesture['expected'] = w.edits.media_clips
        if w.media_dialog is not None and not w.media_dialog.closed:
            w.media_dialog.sync_from_canvas(index)
        self.draw_overlay()
        w.request_frame()

    def move_media(self, event):
        gesture = self.media_drag
        if gesture is None:
            return
        w = self.window
        if (not self.media_ready() or gesture['context'] != self.context()[:3]
                or self.bounds() != gesture['viewport']
                or w.edits.media_clips != gesture['expected']):
            self.media_drag = None
            return
        cue, box = gesture['original'], gesture['box']
        x, y = self.output_point(event.x, event.y)
        px, py = gesture['point']
        width, height = w.edits.encoded_size(self.media)
        mode = gesture['mode']
        if mode == 'move':
            if cue.layout == 'Cutaway':
                proposed = replace(cue, layout='Picture in picture', scale=.60)
                target = media_bounds(proposed, width, height)
                left, top = x - target.width/2, y - target.height/2
            else:
                proposed = cue
                left, top = box.x+x-px, box.y+y-py
        else:
            sx = -1 if 'w' in mode else 1
            sy = -1 if 'n' in mode else 1
            factor = max(.05, 1.0 + ((x-px)*sx/max(2,box.width)
                                    + (y-py)*sy/max(2,box.height))/2)
            original_scale = 1.0 if cue.layout == 'Cutaway' else cue.scale
            proposed = replace(cue, layout='Picture in picture',
                               scale=clamp(original_scale*factor, .05, 1.0))
            target = media_bounds(proposed, width, height)
            left = box.x+box.width-target.width if sx < 0 else box.x
            top = box.y+box.height-target.height if sy < 0 else box.y
        try:
            self.apply_media(with_media_position(proposed, left, top, width, height))
        except ValueError as exc:
            self.window.note.configure(text=str(exc), fg=t.RED)

    def handles(self, rect):
        x1, y1, x2, y2 = rect
        return [('nw', x1, y1), ('ne', x2, y1), ('sw', x1, y2), ('se', x2, y2),
                ('rotate', (x1+x2)/2, y1-18 if y1 >= 25 else y1+18)]

    def draw_overlay(self):
        super().draw_overlay()
        self.draw_media_guide()
        self.delete('visual-guide')
        if not self.visual_ready():
            self.visual_drag = None
            return
        if self.visual_index() is None:
            self.selected_visual = None
            self.visual_drag = None
            return
        try:
            rect = self.visual_rect(self.selected_visual)
        except (ValueError, OSError):
            return  # Missing assets are reported by the existing preview worker.
        if rect is None:
            self.visual_drag = None
            return
        self.create_rectangle(*rect, outline=t.CYAN, width=2, tags='visual-guide')
        for name, x, y in self.handles(rect):
            if name == 'rotate':
                self.create_line(x, rect[1], x, y, fill=t.CYAN, tags='visual-guide')
                self.create_oval(x-5, y-5, x+5, y+5, fill=t.CYAN, outline=t.BG, tags='visual-guide')
            else:
                self.create_rectangle(x-4, y-4, x+4, y+4, fill=t.CYAN, outline=t.BG, tags='visual-guide')
        self.tag_raise('visual-guide')

    def begin(self, event):
        if self.begin_media(event):
            return
        if not self.visual_ready():
            return super().begin(event)
        mode = None
        rect = self.visual_rect(self.selected_visual) if self.visual_index() is not None else None
        if rect:
            radius = min(8, max(2, min(rect[2]-rect[0], rect[3]-rect[1])/4))
            mode = next((name for name, x, y in self.handles(rect)
                         if abs(event.x-x) <= (8 if name == 'rotate' else radius)
                         and abs(event.y-y) <= (8 if name == 'rotate' else radius)), None)
        if mode is None:
            selected = None
            for index in reversed(range(len(self.window.edits.overlays))):
                try:
                    rect = self.visual_rect(self.window.edits.overlays[index])
                except (ValueError, OSError):
                    continue
                if rect and rect[0] <= event.x <= rect[2] and rect[1] <= event.y <= rect[3]:
                    selected = index
                    break
            self.select_visual(selected)
            if selected is None:
                return super().begin(event)
            mode = 'move'
        cue = self.selected_visual
        self.focus_set()
        self.visual_drag = dict(mode=mode, original=cue, box=self.geometry(cue),
                                point=self.output_point(event.x, event.y), context=self.context(),
                                viewport=self.bounds(), expected=self.window.edits.overlays)
        self.window.note.configure(text='Drag to move · corner handles resize · round handle rotates · Esc cancels the drag.', fg=t.CYAN)

    def apply_visual(self, proposed):
        index = self.visual_index()
        if index is None:
            return
        w = self.window
        proposed.validate(w.edits.output_duration(w.cuts.kept_duration(w.trim)))
        cues = list(w.edits.overlays)
        cues[index] = proposed
        w.edits = replace(w.edits, overlays=tuple(cues))
        self.selected_visual = proposed
        if self.visual_drag:
            self.visual_drag['expected'] = w.edits.overlays
        self.sync_dialogs()
        self.draw_overlay()
        w.request_frame()

    def move(self, event):
        if self.media_drag is not None:
            self.move_media(event)
            return
        gesture = self.visual_drag
        if gesture is None:
            return super().move(event)
        if (not self.visual_ready() or self.context() != gesture['context']
                or self.bounds() != gesture['viewport'] or self.window.edits.overlays != gesture['expected']):
            self.visual_drag = None
            return
        cue, box = gesture['original'], gesture['box']
        x, y = self.output_point(event.x, event.y)
        px, py = gesture['point']
        width, height = self.window.edits.encoded_size(self.media)
        mode = gesture['mode']
        if mode == 'rotate':
            cx, cy = box.x+box.side/2, box.y+box.side/2
            delta = math.degrees(math.atan2(y-cy, x-cx)-math.atan2(py-cy, px-cx))
            proposed = replace(cue, rotation=(cue.rotation+delta+180) % 360-180)
        else:
            if mode == 'move':
                left, top = box.x+x-px, box.y+y-py
                proposed = cue
            else:
                sx, sy = (-1 if 'w' in mode else 1), (-1 if 'n' in mode else 1)
                side = max(1, box.side+((x-px)*sx+(y-py)*sy)/2)
                proposed = replace(cue, scale=clamp(cue.scale*side/box.side, .05, .6))
                actual = self.geometry(proposed).side
                left = box.x if sx > 0 else box.x+box.side-actual
                top = box.y if sy > 0 else box.y+box.side-actual
            proposed = positioned(proposed, left, top, width, height, self.output_time(), self.item(cue), self.window.edits.bands(self.media))
        try:
            self.apply_visual(proposed)
        except ValueError as exc:
            self.window.note.configure(text=str(exc), fg=t.RED)

    def finish(self, event=None):
        if self.media_drag is not None:
            if event is not None:
                self.move_media(event)
            self.media_drag = None
            self.draw_overlay()
            return
        if self.visual_drag is not None:
            if event is not None:
                self.move(event)
            self.visual_drag = None
            self.draw_overlay()
            return
        super().finish(event)

    def cancel_visual_drag(self, _=None):
        if self.media_drag is not None:
            gesture, self.media_drag = self.media_drag, None
            if (self.media_ready() and self.context()[:3] == gesture['context']
                    and self.window.edits.media_clips == gesture['expected']):
                self.selected_media_index = gesture['index']
                self.apply_media(gesture['original'])
            self.draw_overlay()
            return 'break'
        gesture, self.visual_drag = self.visual_drag, None
        if (gesture and self.visual_ready() and self.context() == gesture['context']
                and self.window.edits.overlays == gesture['expected']):
            self.apply_visual(gesture['original'])
        else:
            self.select_visual(None)
        return 'break'
