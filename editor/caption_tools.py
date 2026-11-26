"""Timed captions with shared typography controls and an exact draft preview."""
from dataclasses import replace
import tkinter as tk
from tkinter import ttk
from ui import theme as t
from .models import format_time, parse_time
from .text_overlay import Caption
from .typography import CaptionStyle
from .style_preferences import (load_caption_preference, save_caption_preference,
    load_style_library, save_style_library)
from .style_controls import StyleControls, scrollable_styles
from .style_preview import StylePreview
from .edit_history import EditHistory, EditSnapshot


class CaptionDialog(tk.Toplevel):
    def __init__(self, window):
        super().__init__(window)
        self.window=window
        self.title('Timed captions')
        self.configure(bg=t.BG)
        self.geometry(f'{min(940,self.winfo_screenwidth()-60)}x{min(700,self.winfo_screenheight()-90)}')
        self.minsize(800,570);self.transient(window)
        self._loading=True;self._live_id=None;self._dragging=False
        self._bindtag=f'CaptionDrag{id(self)}'
        window.video.bindtags((self._bindtag,)+window.video.bindtags())
        for event,method in (('<Button-1>',self.begin_video_drag),('<B1-Motion>',self.drag_video),('<ButtonRelease-1>',self.end_video_drag)):
            window.video.bind_class(self._bindtag,event,method)
        self.protocol('WM_DELETE_WINDOW',self.destroy)
        self.captions=list(window.edits.text.captions)
        # Pack the footer first: actions remain reachable while Advanced scrolls.
        footer=tk.Frame(self,bg=t.BG);footer.pack(side='bottom',fill='x',padx=14,pady=8)
        self.note=t.label(footer,'New caption · Add saves text and timing. Select a caption to edit it.',9,t.MUTED,wraplength=850,justify='left')
        self.note.pack(fill='x',pady=(0,6))
        actions=tk.Frame(footer,bg=t.BG);actions.pack(fill='x')
        self.actions=[]
        for label,command in (('ADD',lambda:self.save(False)),('UPDATE',lambda:self.save(True)),('APPLY STYLE TO ALL',self.apply_style_all),('REMOVE',self.remove),('DONE',self.destroy)):
            b=t.button(actions,label,command);b.configure(padx=10,pady=6);b.pack(side='left',padx=(0,6));self.actions.append(b)
        head=tk.Frame(self,bg=t.BG);head.pack(fill='x',padx=14,pady=(8,0))
        t.label(head,'CAPTIONS',12,t.CYAN,True).pack(side='left')
        t.button(head,'NEW CAPTION',self.new_caption).pack(side='right')
        self.rows=tk.Listbox(self,height=3,bg=t.CONTROL,fg=t.TEXT,exportselection=False)
        self.rows.pack(fill='x',padx=14,pady=6);self.rows.bind('<<ListboxSelect>>',self.select)
        body=tk.Frame(self,bg=t.BG);body.pack(fill='both',expand=True,padx=14)
        body.columnconfigure(0,weight=2,minsize=280);body.columnconfigure(1,weight=3,minsize=440);body.rowconfigure(0,weight=1)
        left=tk.Frame(body,bg=t.BG);left.grid(row=0,column=0,sticky='nsew',padx=(0,14))
        self.start=tk.StringVar(value=format_time(window.position));self.end=tk.StringVar(value=format_time(min(window.media.duration,window.position+3)))
        self.position=tk.StringVar(value='Bottom')
        self.preview=StylePreview(left,window,self.preview_draft);self.preview.pack(fill='both',expand=True)
        self.preview.bind('<B1-Motion>',self.drag_preview)
        t.label(left,'Drag the preview to position text',9,t.MUTED).pack(anchor='w',pady=4)
        self.input=tk.Text(left,height=3,bg=t.CONTROL,fg=t.TEXT,insertbackground=t.CYAN,wrap='word',undo=True)
        self.input.pack(fill='x',pady=4);self.input.bind('<KeyRelease>',lambda _:self.refresh_preview())
        fields=tk.Frame(left,bg=t.BG);fields.pack(fill='x',pady=4)
        for column,(label,var) in enumerate((('Start',self.start),('End',self.end))):
            fields.columnconfigure(column,weight=1)
            group=tk.Frame(fields,bg=t.BG);group.grid(row=0,column=column,sticky='ew',padx=(0,6))
            t.label(group,label,9,t.MUTED).pack(anchor='w')
            tk.Entry(group,textvariable=var,width=12,bg=t.CONTROL,fg=t.TEXT,insertbackground=t.CYAN).pack(fill='x')
            var.trace_add('write',lambda *_:self.refresh_preview())
        clock='Assembled timeline times' if window.pulse_candidate or window.edits.sequence else 'Source video times'
        t.label(left,clock,9,t.MUTED).pack(anchor='w',pady=4)
        panel,inner=scrollable_styles(body);panel.grid(row=0,column=1,sticky='nsew')
        initial=replace(load_caption_preference(),highlight='')
        if window.edits.comedy_bands:initial=replace(initial,font_size=104)
        self.styles=StyleControls(inner,self.position,self.style_changed,initial,bool(window.edits.comedy_bands))
        self.styles.pack(fill='x')
        self.style_vars=self.styles.variables;self.style_enabled=self.styles.enabled;self.theme=self.styles.theme
        self.picker=self.styles.picker
        self.refresh();self._loading=False;self.refresh_preview()

    def read_style(self):return self.styles.read_style()
    def pick_colour(self,variable):self.styles.pick_colour(variable)
    def choose_preset(self,_=None):self.styles.choose_preset()
    def save_preset(self):self.styles.save_preset()

    def new_caption(self):
        if self._live_id:self.after_cancel(self._live_id);self.apply_selected_style()
        self.rows.selection_clear(0,'end');self.input.delete('1.0','end')
        self.style_vars['highlight'].set('')
        self.start.set(format_time(self.window.position));self.end.set(format_time(min(self.window.media.duration,self.window.position+3)))
        self.note.configure(text='New caption · ADD saves this draft. Existing captions are unchanged.',fg=t.MUTED)
        self.refresh_preview()

    def preview_draft(self):
        if tuple(self.captions)!=self.window.edits.text.captions:
            raise ValueError('The caption timeline changed. Reopen captions to use the updated timing.')
        start,end=parse_time(self.start.get()),parse_time(self.end.get())
        cue=Caption(start,end,self.input.get('1.0','end-1c').strip() or 'YOUR CAPTION',self.position.get(),self.read_style())
        cues=list(self.captions)
        if self.rows.curselection():cues[self.rows.curselection()[0]]=cue
        else:cues.append(cue)
        edits=replace(self.window.edits,text=replace(self.window.edits.text,captions=tuple(cues),safe_area=True))
        return edits,min(end-.01,start+.3)

    def style_changed(self, *_):
        self.refresh_preview()
        if self._loading: return
        if self._live_id: self.after_cancel(self._live_id)
        self._live_id = self.after(220, self.apply_selected_style)

    def apply_selected_style(self):
        self._live_id = None
        if not self.rows.curselection() or self.window.exporter.busy: return
        try:
            index = self.rows.curselection()[0]
            proposed = list(self.captions)
            proposed[index] = replace(proposed[index], style=self.read_style(), position=self.position.get())
            if proposed != self.captions: self.commit(proposed)
            self.note.configure(text='Style updated on the video. Text and timings are unchanged.', fg=t.GREEN)
        except (ValueError, tk.TclError) as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def begin_video_drag(self, event):
        w = self.window
        bounds = w.video.bounds()
        if not bounds or not self.rows.curselection() or w.playing or w.exporter.busy or w.video.source_view: return
        left, top, width, height = bounds
        if not (left <= event.x <= left+width and top <= event.y <= top+height): return
        self._dragging = True
        self.drag_video(event)
        return 'break'

    def drag_video(self, event):
        if not self._dragging: return
        bounds = self.window.video.bounds()
        if bounds:
            left, top, width, height = bounds
            self.place_at((event.x-left)/width, (event.y-top)/height)
        return 'break'

    def end_video_drag(self, event):
        if self._dragging:
            self.drag_video(event)
            self._dragging = False
            return 'break'

    def place_at(self, x, y):
        try:
            style = self.read_style()
            if style is None: return
            if self.window.edits.comedy_bands:
                self.position.set('Top' if y < .5 else 'Bottom')
                bands = self.window.edits.bands(self.window.media)
                band = bands[self.position.get().lower()]
                _, height = self.window.edits.encoded_size(self.window.media)
                self.style_vars['band_y'].set(f'{max(0,min(1,(y*height-band.y)/band.height)):.3f}')
            else:
                # Centre anchors give direct manipulation over the complete safe canvas.
                self.position.set('Centre')
                self.style_vars['alignment'].set('centre')
                self.style_vars['x_offset'].set(f'{max(-.4,min(.4,x-.5)):.3f}')
                self.style_vars['y_offset'].set(f'{max(-.4,min(.4,y-.5)):.3f}')
        except (ValueError, tk.TclError): pass

    def destroy(self):
        self.preview.close()
        if self._live_id:
            self.after_cancel(self._live_id)
            self.apply_selected_style()
        video = self.window.video
        if video.winfo_exists():
            video.bindtags(tuple(tag for tag in video.bindtags() if tag != self._bindtag))
            for event in ('<Button-1>', '<B1-Motion>', '<ButtonRelease-1>'):
                video.unbind_class(self._bindtag, event)
        super().destroy()

    def refresh_preview(self):
        if hasattr(self,'preview') and hasattr(self,'styles'):self.preview.refresh()

    def drag_preview(self,event):
        point=self.preview.point(event)
        if point:self.place_at(*point)

    def apply_style_all(self):
        try:
            if not self.captions:
                raise ValueError('Add a caption first.')
            style = self.read_style()
            self.commit([replace(cue, style=style, position=self.position.get()) for cue in self.captions])
            save_caption_preference(style)
            self.note.configure(text='Style applied to all captions.', fg=t.GREEN)
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def set_style(self,style):
        loading,self._loading=self._loading,True
        self.styles.set_style(style)
        self._loading=loading
        self.style_changed()

    def refresh(self):
        labels=tuple(f'{format_time(cue.start)} – {format_time(cue.end)}  {cue.text.replace(chr(10), " / ")}' for cue in self.captions)
        if self.rows.get(0,'end')==labels:return
        selected = self.rows.curselection()
        self.rows.delete(0, 'end')
        for cue in self.captions:
            self.rows.insert('end', f'{format_time(cue.start)} – {format_time(cue.end)}  {cue.text.replace(chr(10), " / ")}')

        if selected and selected[0] < len(self.captions): self.rows.selection_set(selected[0])

    def select(self, _=None):
        if self.rows.curselection():
            if self._live_id:self.after_cancel(self._live_id);self._live_id=None
            self._loading = True
            cue = self.captions[self.rows.curselection()[0]]
            self.start.set(format_time(cue.start))
            self.end.set(format_time(cue.end))
            self.position.set(cue.position)
            self.set_style(cue.style)
            self.input.delete('1.0', 'end')
            self.input.insert('1.0', cue.text)
            self._loading = False
            self.window.seek(min(cue.end-.01, cue.start+.2))
            self.note.configure(text='Editing selected caption · Style is live. UPDATE saves text and timing.',fg=t.MUTED)
            self.refresh_preview()

    def commit(self, proposed):
        w = self.window
        if w.closing or w.exporter.busy:raise ValueError('Wait for export to finish before changing captions.')
        if tuple(self.captions)!=w.edits.text.captions:
            raise ValueError('The caption timeline changed. Reopen captions to use the updated timing.')
        edits = replace(w.edits, text=replace(w.edits.text, captions=tuple(proposed), safe_area=True))
        edits.validate(w.media)
        w.stop_play()
        before = EditSnapshot(w.trim, w.cuts, w.edits)
        if w.timeline_history is None or w.timeline_history.current != before:
            w.timeline_history = EditHistory(before)
        w.edits = edits
        w.timeline_history.record(EditSnapshot(w.trim, w.cuts, edits))
        w.update_timeline()
        self.captions = proposed
        self.refresh()
        w.request_frame()

    def save(self, update):
        try:
            style = self.read_style()
            cue = Caption(parse_time(self.start.get()), parse_time(self.end.get()),
                          self.input.get('1.0', 'end-1c'), self.position.get(), style)
            proposed = list(self.captions)
            if update:
                if not self.rows.curselection():
                    raise ValueError('Select a caption to update.')
                proposed[self.rows.curselection()[0]] = cue
            else:
                proposed.append(cue)
            self.commit(proposed)
            if not update:
                self.rows.selection_clear(0,'end');self.rows.selection_set(len(proposed)-1);self.select()
            save_caption_preference(style)
            self.note.configure(text='Caption saved.', fg=t.GREEN)
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def remove(self):
        if self.rows.curselection():
            proposed = list(self.captions)
            del proposed[self.rows.curselection()[0]]
            try:self.commit(proposed)
            except ValueError as exc:self.note.configure(text=str(exc),fg=t.RED)
