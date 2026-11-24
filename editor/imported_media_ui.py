"""Small, separate photo/video editor for Quick Edit's MEDIA timeline track."""
from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from ui import theme as t
from .imported_media import create_clip, validate_clips, MAX_CLIPS, LAYOUTS
from .models import format_time, parse_time


class ImportedMediaDialog(tk.Toplevel):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.closed = False
        self.title('PULSE // CAPTURE — PHOTOS & VIDEO')
        self.geometry('790x590')
        self.minsize(650, 500)
        self.configure(bg=t.BG)
        self.transient(window)
        self.protocol('WM_DELETE_WINDOW', self.close)
        window.auto_children.add(self)

        top = tk.Frame(self, bg=t.BG)
        top.pack(fill='x', padx=18, pady=(14, 9))
        t.label(top, 'MEDIA TIMELINE', 18, t.TEXT, True).pack(side='left')
        t.button(top, 'ADD PHOTO', lambda: self.add('photo'), accent=True).pack(side='right', padx=(8, 0))
        t.button(top, 'ADD VIDEO', lambda: self.add('video')).pack(side='right')
        t.label(self, 'Select media on the preview to move or resize it. The MEDIA track controls duration.',
                9, t.MUTED).pack(anchor='w', padx=18, pady=(0, 9))

        frame = tk.Frame(self, bg=t.BG)
        frame.pack(fill='both', expand=True, padx=18)
        self.items = tk.Listbox(frame, height=6, bg=t.CONTROL, fg=t.TEXT,
                                selectbackground='#285464', exportselection=False,
                                font=(t.FONT, -12), borderwidth=0)
        self.items.pack(fill='both', expand=True)
        self.items.bind('<<ListboxSelect>>', self.select_clip)

        controls = tk.Frame(self, bg=t.PANEL)
        controls.pack(fill='x', padx=18, pady=(10, 0))
        self.vars = {}
        for col, (key, caption) in enumerate((
            ('start', 'TIMELINE START'), ('duration', 'DURATION'),
            ('source_in', 'VIDEO SOURCE START'))):
            group = tk.Frame(controls, bg=t.PANEL)
            group.grid(row=0, column=col, padx=8, pady=8, sticky='ew')
            controls.columnconfigure(col, weight=1)
            t.label(group, caption, 9, t.MUTED, True).pack(anchor='w')
            var = tk.StringVar(value='0:00.000')
            self.vars[key] = var
            tk.Entry(group, textvariable=var, bg=t.CONTROL, fg=t.TEXT,
                     insertbackground=t.CYAN, relief='flat', font=(t.MONO, -14)).pack(fill='x', ipady=5, pady=(4, 0))
        group = tk.Frame(controls, bg=t.PANEL)
        group.grid(row=1, column=0, columnspan=3, sticky='ew', padx=8, pady=(0, 9))
        t.label(group, 'DISPLAY', 9, t.MUTED, True).pack(side='left', padx=(0, 10))
        self.layout = tk.StringVar(value=LAYOUTS[0])
        layout = ttk.Combobox(group, textvariable=self.layout, state='readonly', values=LAYOUTS, width=22)
        layout.pack(side='left')
        t.label(group, 'Cutaway fills the screen; PiP supports dragging.',
                9, t.MUTED).pack(side='left', padx=10)
        for col, (key, title, initial) in enumerate((
            ('x', 'X POSITION %', '100'), ('y', 'Y POSITION %', '0'),
            ('scale', 'SIZE %', '38'))):
            item = tk.Frame(controls, bg=t.PANEL)
            item.grid(row=2, column=col, sticky='ew', padx=8, pady=(0, 9))
            t.label(item, title, 9, t.MUTED, True).pack(anchor='w')
            var = tk.StringVar(value=initial)
            self.vars[key] = var
            tk.Entry(item, textvariable=var, bg=t.CONTROL, fg=t.TEXT,
                     insertbackground=t.CYAN, relief='flat',
                     font=(t.MONO, -14)).pack(fill='x', ipady=5, pady=(4, 0))

        buttons = tk.Frame(self, bg=t.BG)
        buttons.pack(fill='x', padx=18, pady=(11, 0))
        t.button(buttons, 'APPLY CHANGES', self.apply, accent=True).pack(side='left')
        t.button(buttons, 'REMOVE SELECTED', self.remove).pack(side='left', padx=8)
        t.button(buttons, 'SEEK TO CLIP', self.seek_clip).pack(side='left')
        t.button(buttons, 'CLOSE', self.close).pack(side='right')
        self.message = t.label(
            self, 'All times are on the edited output timeline. Imported video is muted in this first version.',
            9, t.MUTED, wraplength=740, justify='left')
        self.message.pack(fill='x', padx=18, pady=(9, 14))
        self.refresh()

    def total(self):
        w = self.window
        return w.edits.output_duration(w.cuts.kept_duration(w.trim))

    def _set_clips(self, clips, selected=None):
        w = self.window
        if w.exporter.busy or w.closing:
            raise ValueError('Wait until export finishes before changing media.')
        total = self.total()
        validate_clips(clips, total)
        proposed = replace(w.edits, media_clips=tuple(clips))
        proposed.validate(w.media)
        w.stop_play()
        w.edits = proposed
        # Edits made in this dialog begin a new undo history. Earlier saved
        # timeline drags are never replayed over a separately changed clip list.
        w.timeline_history = None
        w.update_timeline()
        w.request_frame()
        self.refresh(selected)

    def refresh(self, selected=None):
        if self.closed or not self.winfo_exists():
            return
        current = selected
        if current is None:
            old = self.items.curselection()
            current = old[0] if old else None
        self.items.delete(0, 'end')
        for i, cue in enumerate(self.window.edits.media_clips):
            self.items.insert('end',
                f'{i + 1}. {cue.title}  |  {cue.kind.upper()}  |  '
                f'{format_time(cue.start)}–{format_time(cue.end)}  |  {cue.layout}')
        count = self.items.size()
        if count and current is not None:
            current = min(current, count - 1)
            self.items.selection_set(current)
            self.items.see(current)
            self.select_clip()
        else:
            self.window.video.select_media(None, notify=False)

    def chosen_index(self):
        indices = self.items.curselection()
        if not indices:
            raise ValueError('Choose a clip from the list first.')
        return indices[0]

    def select_clip(self, _event=None):
        try:
            cue = self.window.edits.media_clips[self.chosen_index()]
        except (ValueError, IndexError):
            return
        self.vars['start'].set(format_time(cue.start))
        self.vars['duration'].set(format_time(cue.duration))
        self.vars['source_in'].set(format_time(cue.source_in))
        self.layout.set(cue.layout)
        self.window.video.select_media(self.chosen_index(), notify=False)
        for key in ('x', 'y', 'scale'):
            self.vars[key].set(f'{getattr(cue, key) * 100:.1f}')

    def sync_from_canvas(self, index):
        if self.closed or not self.winfo_exists():
            return
        self.items.selection_clear(0, 'end')
        if index is not None and 0 <= index < self.items.size():
            self.items.selection_set(index)
            self.items.see(index)
            self.select_clip()

    def add(self, kind):
        try:
            w = self.window
            if w.exporter.busy:
                raise ValueError('Wait for export to finish.')
            choices = [('Photos', '*.png *.jpg *.jpeg *.webp')] if kind == 'photo' else [
                ('Video clips', '*.mp4 *.mov *.mkv *.webm')]
            paths = filedialog.askopenfilenames(parent=self, title='Choose your own or licensed media',
                                                 filetypes=choices)
            if not paths:
                return
            cues = list(w.edits.media_clips)
            at = w.cuts.source_elapsed(w.position, w.trim) / w.edits.speed
            total = self.total()
            for path in paths:
                if len(cues) >= MAX_CLIPS:
                    raise ValueError(f'Maximum {MAX_CLIPS} media clips.')
                clip = create_clip(w.backend.ffprobe, path, at, total)
                cues.append(clip)
                at = min(total, clip.end)
            self._set_clips(cues, len(cues)-1)
            self.message.configure(text=f'Imported {len(paths)} file(s). Drag their MEDIA blocks to change timing.',
                                   fg=t.CYAN)
        except (ValueError, OSError) as exc:
            self.message.configure(text=str(exc), fg=t.RED)

    def apply(self):
        try:
            index = self.chosen_index()
            cues = list(self.window.edits.media_clips)
            original = cues[index]
            start = parse_time(self.vars['start'].get())
            length = parse_time(self.vars['duration'].get())
            source_in = parse_time(self.vars['source_in'].get()) if original.kind == 'video' else 0
            try:
                x = float(self.vars['x'].get()) / 100
                y = float(self.vars['y'].get()) / 100
                size = float(self.vars['scale'].get()) / 100
            except ValueError as exc:
                raise ValueError('Enter numeric X, Y and Size percentages.') from exc
            cues[index] = replace(original, start=start, end=start + length,
                                  source_in=source_in, layout=self.layout.get(),
                                  x=x, y=y, scale=size)
            self._set_clips(cues, index)
            self.message.configure(text='Media timing updated. The original file was not modified.', fg=t.CYAN)
        except (ValueError, IndexError) as exc:
            self.message.configure(text=str(exc), fg=t.RED)

    def remove(self):
        try:
            index = self.chosen_index()
            cues = list(self.window.edits.media_clips)
            cues.pop(index)
            self._set_clips(cues, min(index, len(cues)-1) if cues else None)
            self.message.configure(text='Clip removed from this edit. The source file is untouched.', fg=t.CYAN)
        except (ValueError, IndexError) as exc:
            self.message.configure(text=str(exc), fg=t.RED)

    def seek_clip(self):
        try:
            cue = self.window.edits.media_clips[self.chosen_index()]
            self.window.seek_output_time(cue.start)
        except (ValueError, IndexError) as exc:
            self.message.configure(text=str(exc), fg=t.RED)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.window.auto_children.discard(self)
        self.destroy()
