"""Trim, removed sections, draft cut markers, and a separate playhead."""
import tkinter as tk
from ui import theme as t
from .models import TrimRange, format_time


class Timeline(tk.Canvas):
    """Source-clock trim row and output-clock draggable visual/audio tracks."""
    TRACK_TOP = 68
    TRACK_HEIGHT = 24
    TRACK_LABELS = ('VIDEO', 'MEDIA', 'CAPTIONS', 'EMOJIS / GIFS', 'SFX', 'VOICE', 'MUSIC', 'MOTION')

    def __init__(self, parent, on_seek, on_trim, on_clip_begin=None,
                 on_clip_change=None, on_clip_end=None):
        super().__init__(parent, height=273, bg=t.BG, highlightthickness=0, cursor='hand2')
        self.on_seek, self.on_trim = on_seek, on_trim
        self.on_clip_begin = on_clip_begin
        self.on_clip_change = on_clip_change
        self.on_clip_end = on_clip_end
        self.clip_blocks = ()
        self.output_duration = 0.0
        self.clip_drag = None
        self.view_start = 0.0
        self.view_span = 0.0
        self.media = self.trim = None
        self.cuts = None
        self.privacy = None
        self.cut_draft = (None, None)
        self.crop_keyframes = ()
        self.reaction_markers = ()
        self.position = 0
        self.enabled = True
        self.drag = None
        self.bind('<Configure>', lambda _: self.draw())
        self.bind('<Button-1>', self.begin)
        self.bind('<B1-Motion>', self.move)
        self.bind('<ButtonRelease-1>', self.release)
        self.bind('<MouseWheel>', self.zoom_wheel)

    def x(self, seconds):
        return 14 + seconds / self.media.duration * max(1, self.winfo_width() - 28)

    def seconds(self, x):
        return max(0, min(self.media.duration, (x - 14) / max(1, self.winfo_width() - 28) * self.media.duration))

    def visible_span(self):
        if not self.output_duration:return 1.0
        return min(self.output_duration,self.view_span or self.output_duration)

    def block_x(self, seconds):
        return 14 + (seconds-self.view_start) / self.visible_span() * max(1, self.winfo_width()-28)

    def block_seconds(self, x):
        return max(0, min(self.output_duration,
                   self.view_start+(x-14)/max(1,self.winfo_width()-28)*self.visible_span()))

    def zoom_wheel(self,event):
        if not self.media or self.output_duration<=0:return
        old=self.visible_span()
        factor=.75 if event.delta>0 else 1/.75
        minimum=min(self.output_duration,2.0)
        updated=max(minimum,min(self.output_duration,old*factor))
        centre=self.block_seconds(event.x)
        ratio=max(0,min(1,(event.x-14)/max(1,self.winfo_width()-28)))
        self.view_start=max(0,min(self.output_duration-updated,centre-ratio*updated))
        self.view_span=updated
        self.draw()
        return 'break' 

    def block_hit(self, x, y):
        if not self.media or self.output_duration <= 0:
            return None
        track = int((y-self.TRACK_TOP)//self.TRACK_HEIGHT)
        if track < 0 or track >= len(self.TRACK_LABELS):
            return None
        for block in reversed(self.clip_blocks):
            if block.track != track or block.kind not in ('caption','overlay','sound','media'):
                continue
            left, right = self.block_x(block.start), self.block_x(block.end)
            if left-4 <= x <= right+4:
                edge = min(9, max(4,(right-left)/4))
                mode = ('left' if x <= left+edge else
                        'right' if x >= right-edge else 'move')
                return block, mode
        return None

    def draw(self):
        self.delete('all')
        if not self.media:
            return
        right = self.winfo_width() - 14
        self.create_rectangle(14, 12, right, 36, fill=t.CONTROL, outline='')
        start, end = self.x(self.trim.start), self.x(self.trim.end)
        self.create_rectangle(start, 12, end, 36, fill='#17464f', outline=t.CYAN)

        if self.cuts:
            for cut in self.cuts.visible_ranges(self.trim):
                left, cut_right = self.x(cut.start), self.x(cut.end)
                self.create_rectangle(left, 12, cut_right, 36, fill='#4b2028',
                                      outline=t.RED, width=1, tags='cut')
                if cut_right-left > 32:
                    self.create_text((left+cut_right)/2, 24, text='CUT', fill=t.TEXT,
                                     font=(t.FONT, -9, 'bold'), tags='cut')

        if self.privacy:
            for mask in self.privacy.masks:
                self.create_line(self.x(mask.start), 46, self.x(mask.end), 46,
                                 fill=t.CYAN, width=2, tags='privacy-range')

        # Cyan diamonds mark source-time crop keys; click their position
        # to seek, then reposition the cyan crop frame.
        for key in self.crop_keyframes:
            if self.trim.start <= key.time <= self.trim.end:
                mark = self.x(key.time)
                self.create_polygon(mark, 41, mark+5, 46, mark, 51, mark-5, 46,
                                    fill=t.CYAN, outline=t.BG, tags='crop-keyframe')

        for seconds, label in self.reaction_markers:
            mark = self.x(seconds)
            self.create_line(mark, 12, mark, 38, fill='#ffd83d', width=2, tags='reaction-cue')
            self.create_text(mark, 43, text=label, fill='#ffd83d', font=(t.FONT, -8, 'bold'), tags='reaction-cue')

        # Output-time tracks have their own time scale (speed and removed cuts).
        # Keep the source-time trim handles above, unchanged.
        if self.output_duration > 0:
            right=max(15,self.winfo_width()-14)
            for track,label in enumerate(self.TRACK_LABELS):
                top=self.TRACK_TOP+track*self.TRACK_HEIGHT
                self.create_rectangle(14,top,right,top+self.TRACK_HEIGHT-1,
                                      fill=('#111e28' if track%2==0 else '#172430'),outline='')
                self.create_text(18,top+3,anchor='nw',text=label,fill='#667b89',
                                 font=(t.FONT,-8,'bold'))
            for block in self.clip_blocks:
                if not 0 <= block.track < len(self.TRACK_LABELS):continue
                if block.end < self.view_start or block.start > self.view_start+self.visible_span():continue
                a=max(14,self.block_x(block.start));b=min(right,self.block_x(block.end))
                y=self.TRACK_TOP+block.track*self.TRACK_HEIGHT
                if b-a < 4:b=a+4
                editable=block.kind in ('caption','overlay','sound','media')
                fill=('#185e70' if editable else '#344653')
                stroke=('#60e2ff' if editable else '#526474')
                self.create_rectangle(a,y+2,b,y+21,fill=fill,outline=stroke,width=1)
                if editable:
                    self.create_line(a+4,y+5,a+4,y+18,fill='#8aebff',width=2)
                    self.create_line(b-4,y+5,b-4,y+18,fill='#8aebff',width=2)
                if b-a > 40:
                    text=block.label[:max(1,int((b-a-13)/7))]
                    self.create_text(a+9,y+11,text=text,anchor='w',fill='#f0fbff',
                                     font=(t.FONT,-9,'bold'))
        draft_start, draft_end = self.cut_draft
        for value, label in ((draft_start, 'S'), (draft_end, 'E')):
            if value is not None:
                point = self.x(value)
                self.create_line(point, 7, point, 41, fill=t.RED, width=2, dash=(3, 2), tags='cut-draft')
                self.create_text(point, 5, text=label, anchor='s', fill=t.RED,
                                 font=(t.FONT, -9, 'bold'), tags='cut-draft')

        for point in (start, end):
            self.create_rectangle(point-5, 8, point+5, 40, fill=t.CYAN, outline='')
            self.create_line(point, 18, point, 30, fill=t.BG, width=2)
        point = self.x(self.position)
        self.create_line(point, 5, point, 43, fill=t.TEXT, width=2, tags='playhead-line')
        self.create_polygon(point-5, 2, point+5, 2, point, 8, fill=t.TEXT, tags='playhead-head')
        self.create_text(14, 55, text='0:00', anchor='w', fill=t.MUTED, font=(t.MONO, -11))
        self.create_text(right, 55, text=format_time(self.media.duration), anchor='e', fill=t.MUTED, font=(t.MONO, -11))

    def move_playhead(self, position):
        self.position=position
        if not self.media:return
        point=self.x(position)
        self.coords('playhead-line',point,5,point,43)
        self.coords('playhead-head',point-5,2,point+5,2,point,8)

    def release(self, _event):
        if self.clip_drag is not None:
            self.clip_drag = None
            if self.on_clip_end:
                self.on_clip_end()
        self.drag = None

    def begin(self, event):
        if not self.media or not self.enabled:
            return
        hit=self.block_hit(event.x,event.y)
        if hit is not None:
            block, mode=hit
            self.clip_drag=(block.key,mode,block.start,block.end,
                            block.start if mode=='left' else
                            block.end if mode=='right' else self.block_seconds(event.x))
            self.drag='clip'
            if self.on_clip_begin:self.on_clip_begin(block.key)
            return
        if event.y >= self.TRACK_TOP:
            # Clicking an empty track seeks on the output clock.
            self.drag = 'output_seek'
            self.move(event)
            return
        distances = {'start': abs(event.x-self.x(self.trim.start)), 'end': abs(event.x-self.x(self.trim.end))}
        nearest = min(distances, key=distances.get)
        self.drag = nearest if distances[nearest] <= 13 else 'seek'
        self.move(event)

    def move(self, event):
        if not self.drag or not self.enabled:
            return
        if self.drag=='clip':
            if self.clip_drag is None or self.on_clip_change is None:return
            key,mode,start,end,anchor=self.clip_drag
            delta=self.block_seconds(event.x)-anchor
            minimum=max(0.001,1/max(1,self.media.fps))
            if mode=='move':
                duration=end-start
                new_start=max(0,min(self.output_duration-duration,start+delta))
                left,right=new_start,new_start+duration
            elif mode=='left':
                left=max(0,min(end-minimum,start+delta));right=end
            else:
                left=start;right=max(start+minimum,min(self.output_duration,end+delta))
            self.on_clip_change(key,left,right)
            return
        if self.drag=='output_seek':
            if self.on_clip_change is not None and hasattr(self,'on_output_seek'):
                self.on_output_seek(self.block_seconds(event.x))
            return
        value = self.seconds(event.x)
        gap = min(1 / self.media.fps, self.media.duration)
        if self.drag == 'start':
            self.on_trim(TrimRange(min(value, self.trim.end-gap), self.trim.end), 'start')
        elif self.drag == 'end':
            self.on_trim(TrimRange(self.trim.start, max(value, self.trim.start+gap)), 'end')
        else:
            self.on_seek(value)
