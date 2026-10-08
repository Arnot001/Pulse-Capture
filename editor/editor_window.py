"""Quick Edit shell; focused panels and services own editing behavior."""
import os
from dataclasses import replace
from pathlib import Path
from queue import Queue, Empty
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
from ui import theme as t
from .export_job import ExportJob
from .media import probe_media
from .models import TrimRange, format_time, parse_time
from .preview import Preview
from .timeline import Timeline
from .privacy_preview import PrivacyPreview
from .overlay_tools import OverlayTools
from .transforms import EditOptions, Branding, FORMATS, CORNERS, SIZES


class EditorWindow(tk.Toplevel):
    def __init__(self, parent, path, backend, on_close=None):
        super().__init__(parent)
        self.title('PULSE // CAPTURE — QUICK EDIT')
        self.configure(bg=t.BG)
        self.geometry(f'980x{min(850, self.winfo_screenheight()-100)}')
        self.minsize(760, 700)
        self.path, self.backend, self.on_close = Path(path), backend, on_close
        self.media = self.trim = self.preview = None
        self.exporter = ExportJob(backend)
        self.metadata = Queue()
        self.closed = self.closing = self.playing = False
        self.position, self.token = 0.0, 0
        self.last_export = None
        self.output_folder = self.path.parent
        self._seek_id = self._poll_id = self._play_id = None
        self._photo = None
        self.controls = []
        self.edits = EditOptions()
        self.tool = tk.StringVar(value='TRIM')
        self.format_choice = tk.StringVar(value='Original')
        self.brand_on = tk.BooleanVar(value=False)
        self.brand_corner = tk.StringVar(value='Bottom right')
        self.brand_size = tk.StringVar(value='Small')
        self.panels = {}
        self.brand_segments = []
        self.start_text, self.end_text = tk.StringVar(value='0:00.000'), tk.StringVar(value='0:00.000')
        self._build()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self._poll_id = self.after(60, self.poll)
        def load():
            try:
                self.metadata.put((probe_media(backend.ffprobe, self.path), None))
            except Exception as exc:
                self.metadata.put((None, str(exc)))
        threading.Thread(target=load, daemon=True).start()

    def _build(self):
        tk.Frame(self, height=3, bg=t.CYAN).pack(fill='x')
        header = tk.Frame(self, bg=t.BG)
        header.pack(fill='x', padx=28, pady=(14, 6))
        t.label(header, 'PULSE', 21, bold=True).pack(side='left')
        t.label(header, ' // CAPTURE', 15, t.CYAN).pack(side='left')
        t.label(header, 'QUICK EDIT', 10, t.MUTED, True).pack(side='right')
        intro = tk.Frame(self, bg=t.BG)
        intro.pack(fill='x', padx=28, pady=(0, 12))
        self.source_label = t.label(intro, self.path.name, 9, t.MUTED, anchor='w')
        self.source_label.pack(fill='x', pady=(4, 0))

        # Bottom controls stay reachable when the window is resized.
        bottom = tk.Frame(self, bg=t.BG)
        bottom.pack(side='bottom', fill='x', padx=28, pady=(0, 18))
        self.note = t.label(bottom, 'Opening your video…', 10, t.MUTED, anchor='w', justify='left', wraplength=850)
        self.note.pack(fill='x', pady=(8, 6))
        ttk.Style(self).configure('Pulse.Horizontal.TProgressbar', background=t.CYAN,
                                 troughcolor=t.CONTROL, bordercolor=t.CONTROL,
                                 lightcolor=t.CYAN, darkcolor=t.CYAN, thickness=5)
        self.progress = ttk.Progressbar(bottom, mode='determinate', maximum=1,
                                        style='Pulse.Horizontal.TProgressbar')
        self.progress.pack(fill='x', pady=(0, 10))
        actions = tk.Frame(bottom, bg=t.BG)
        actions.pack(fill='x')
        self.export_button = t.button(actions, 'EXPORT VIDEO  ↗', self.export, accent=True,
                                       font=(t.FONT, -16, 'bold'))
        self.export_button.configure(pady=12, state='disabled')
        self.export_button.pack(side='left', fill='x', expand=True)
        self.cancel_button = t.button(actions, 'CANCEL EXPORT', self.cancel_export)
        self.open_button = t.button(actions, 'OPEN FOLDER', self.open_folder)
        self.open_button.pack(side='right', padx=(10, 0))
        destination = tk.Frame(bottom, bg=t.BG)
        destination.pack(fill='x', pady=(7, 0))
        self.destination = t.label(destination, 'New copy beside your original · Original stays untouched', 9, t.MUTED)
        self.destination.pack(side='left')
        self.change_folder_button = t.button(destination, 'CHANGE FOLDER', self.change_folder)
        self.change_folder_button.configure(pady=2, font=(t.FONT, -10, 'bold'))
        self.change_folder_button.pack(side='right')
        self.controls.append(self.change_folder_button)

        tool_area = tk.Frame(bottom, bg=t.BG)
        tool_area.pack(side='top', fill='x', before=self.note, pady=(8, 0))
        tabs = t.Segments(tool_area, self.tool, [(v, v) for v in ('TRIM', 'FORMAT', 'CROP', 'BRAND', 'TEXT', 'PRIVACY')], self.show_tool)
        tabs.pack(fill='x', pady=(0, 8))
        self.controls.extend(b for _, b in tabs.buttons)
        # A fixed, compact tool area keeps the preview stable when switching tools.
        panel_area = tk.Frame(tool_area, bg=t.PANEL, height=122)
        panel_area.pack(fill='x')
        panel_area.pack_propagate(False)
        for name in ('TRIM', 'FORMAT', 'CROP', 'BRAND', 'TEXT', 'PRIVACY'):
            self.panels[name] = tk.Frame(panel_area, bg=t.PANEL)
        row = self.panels['TRIM']
        row.pack(fill='both', expand=True, padx=12, pady=10)
        for column, (title, variable, bound) in enumerate((('Start', self.start_text, 'start'), ('End', self.end_text, 'end'))):
            group = tk.Frame(row, bg=t.PANEL)
            group.grid(row=0, column=column, sticky='ew', padx=(0, 18))
            row.columnconfigure(column, weight=1)
            t.label(group, title, 10, bold=True).pack(anchor='w')
            inner = tk.Frame(group, bg=t.PANEL)
            inner.pack(fill='x', pady=(5, 0))
            entry = tk.Entry(inner, textvariable=variable, bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN,
                             relief='flat', width=13, font=(t.MONO, -17), disabledbackground=t.CONTROL)
            entry.pack(side='left', ipady=7)
            entry.bind('<Return>', lambda _: self.commit_entries())
            entry.bind('<FocusOut>', lambda _: self.commit_entries())
            button = t.button(inner, 'USE PLAYHEAD', lambda b=bound: self.use_playhead(b))
            button.configure(font=(t.FONT, -10, 'bold'), padx=8)
            button.pack(side='left', padx=(8, 0))
            self.controls.extend((entry, button))
        self.reset_button = t.button(row, 'RESET', self.reset_trim)
        self.reset_button.grid(row=0, column=2, sticky='se')
        self.controls.append(self.reset_button)
        self.selection_label = t.label(row, 'Drag the cyan handles or enter Start and End.', 9, t.MUTED)
        self.selection_label.grid(row=1, column=0, columnspan=3, sticky='w', pady=(8, 0))
        self.build_tools()
        self.overlay_tools = OverlayTools(self)
        for widget in self.controls:
            widget.configure(state='disabled')

        preview_area = tk.Frame(self, bg=t.BG)
        preview_area.pack(fill='both', expand=True, padx=28)
        self.video = PrivacyPreview(preview_area, self.crop_changed, self.overlay_tools.mask_changed, bg='#060a10', highlightbackground=t.LINE, highlightthickness=1, height=260)
        preview_area.rowconfigure(0, weight=1)
        preview_area.columnconfigure(0, weight=1)
        self.video.grid(row=0, column=0, sticky='nsew')
        self.video.bind('<Configure>', self.resize_preview)
        self.video.create_text(350, 120, text='Opening your video…', fill=t.MUTED, tags='placeholder')
        transport = tk.Frame(preview_area, bg=t.BG)
        transport.grid(row=1, column=0, sticky='ew', pady=(8, 0))
        self.play_button = t.button(transport, '▶  PREVIEW TRIM', self.toggle_play)
        self.play_button.configure(state='disabled')
        self.play_button.pack(side='left')
        self.clock = t.label(transport, '0:00.000 / 0:00.000', 11, t.TEXT)
        self.clock.pack(side='left', padx=16)
        self.preview_note = t.label(transport, 'Silent preview · Export keeps audio', 9, t.MUTED)
        self.preview_note.pack(side='right')
        self.timeline = Timeline(preview_area, self.seek, self.drag_trim)
        self.timeline.grid(row=2, column=0, sticky='ew')

    def add_segments(self, parent, variable, choices, command):
        segments = t.Segments(parent, variable, choices, command)
        segments.pack(fill='x', pady=(0, 6))
        self.controls.extend(b for _, b in segments.buttons)
        return segments

    def build_tools(self):
        panel = self.panels['FORMAT']
        self.add_segments(panel, self.format_choice,
                          [(v, v.replace(' ', '\n', 1)) for v in FORMATS], self.format_changed)
        t.label(panel, 'Choose your shape. Use Crop to move the frame.', 9, t.MUTED).pack(anchor='w')
        panel = self.panels['CROP']
        self.crop_hint = t.label(panel, 'Choose a format first to crop your video.', 10, t.MUTED)
        self.crop_hint.pack(anchor='w', pady=(0, 8))
        actions = tk.Frame(panel, bg=t.PANEL)
        actions.pack(fill='x')
        for label, command in [('CHOOSE FORMAT', lambda: self.select_tool('FORMAT')),
                               ('CENTRE CROP', self.center_crop),
                               ('VIEW RESULT', lambda: self.select_tool('FORMAT'))]:
            button = t.button(actions, label, command)
            button.pack(side='left', padx=(0, 8))
            self.controls.append(button)
        panel = self.panels['BRAND']
        row = tk.Frame(panel, bg=t.PANEL)
        row.pack(fill='x')
        toggle = tk.Frame(row, bg=t.PANEL)
        toggle.pack(side='left', padx=(0, 14))
        self.add_segments(toggle, self.brand_on, [(False, 'OFF'), (True, 'ON')], self.brand_changed)
        sizes = tk.Frame(row, bg=t.PANEL)
        sizes.pack(side='left', fill='x', expand=True)
        self.brand_segments.append(self.add_segments(sizes, self.brand_size,
                                  [(v, v) for v in SIZES], self.brand_changed))
        self.brand_segments.append(self.add_segments(panel, self.brand_corner,
                                  [(v, v) for v in CORNERS], self.brand_changed))
        t.label(panel, 'Adds a new logo. A logo already in the recording cannot be removed.',
                9, t.MUTED).pack(anchor='w')

    def select_tool(self, name):
        self.tool.set(name)
        self.show_tool()

    def show_tool(self):
        self.stop_play()
        for panel in self.panels.values():
            panel.pack_forget()
        self.panels[self.tool.get()].pack(fill='both', expand=True, padx=12, pady=10)
        self.video.active = self.tool.get() == 'CROP'
        self.video.drag = None
        self.overlay_tools.refresh()
        self.request_frame()

    def format_changed(self):
        if not self.media or self.exporter.busy:
            return
        try:
            if self.format_choice.get() != self.edits.preset:
                self.edits = self.edits.with_format(self.media, self.format_choice.get())
            self.video.crop = self.edits.crop
            self.overlay_tools.refresh()
            self.crop_hint.configure(text='Drag the cyan frame to keep what matters. Arrow keys fine-tune.'
                                     if self.edits.crop else 'Original keeps the full frame. Choose a format to crop.')
            self.stop_play()
            self.request_frame()
        except ValueError as exc:
            self.format_choice.set(self.edits.preset)
            self.note.configure(text=str(exc), fg=t.RED)

    def crop_changed(self, crop):
        if self.exporter.busy or self.closing:
            return
        self.edits = replace(self.edits, crop=crop)
        self.video.crop = crop
        self.overlay_tools.refresh()

    def center_crop(self):
        self.edits = self.edits.with_format(self.media, self.edits.preset)
        self.video.crop = self.edits.crop
        self.overlay_tools.refresh()

    def update_brand_controls(self):
        enabled = bool(self.media and not self.exporter.busy and self.brand_on.get())
        for segments in self.brand_segments:
            segments.enable(enabled)

    def brand_changed(self):
        self.edits = replace(self.edits, branding=Branding(self.brand_on.get(),
                             self.brand_corner.get(), self.brand_size.get()))
        self.update_brand_controls()
        self.stop_play()
        self.request_frame()

    def resize_preview(self, _=None):
        self.video.coords('placeholder', self.video.winfo_width()/2, self.video.winfo_height()/2)
        self.video.coords('frame', self.video.winfo_width()/2, self.video.winfo_height()/2)
        self.video.drag = None
        self.video.gesture = self.video.candidate = None
        self.video.draw_overlay()
        if self.preview and not self.playing:
            self.request_frame()

    def request_frame(self):
        if not self.preview or self.closed or self.closing:
            return
        self.token += 1
        token = self.token
        if self._seek_id:
            self.after_cancel(self._seek_id)
        def send():
            self._seek_id = None
            self.preview.request(token, self.position, self.video.winfo_width()-4, self.video.winfo_height()-4,
                                 self.edits, self.tool.get() == 'CROP')
        self._seek_id = self.after(90 if not self.playing else 1, send)

    def seek(self, position):
        self.stop_play()
        self.position = max(0, min(position, self.media.duration))
        self.update_timeline()
        self.request_frame()

    def update_timeline(self):
        self.timeline.media, self.timeline.trim, self.timeline.position = self.media, self.trim, self.position
        self.timeline.draw()
        self.clock.configure(text=f'{format_time(self.position)} / {format_time(self.media.duration)}')

    def update_trim(self, trim):
        trim.validate(self.media)
        self.trim = trim
        self.start_text.set(format_time(trim.start))
        self.end_text.set(format_time(trim.end))
        self.selection_label.configure(text=f'Keeping {format_time(trim.duration)}  ·  Drag the cyan handles to adjust.')
        self.note.configure(text='Ready to export. Your original recording stays untouched.', fg=t.MUTED)
        self.export_button.configure(state='normal')
        self.update_timeline()

    def commit_entries(self):
        if not self.media or self.exporter.busy or self.closing:
            return False
        try:
            self.overlay_tools.commit_text()
            self.edits.validate(self.media)
            trim = TrimRange(parse_time(self.start_text.get()), parse_time(self.end_text.get()))
            self.update_trim(trim)
            return True
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)
            self.export_button.configure(state='disabled')
            return False

    def use_playhead(self, bound):
        self.stop_play()
        variable = self.start_text if bound == 'start' else self.end_text
        variable.set(format_time(self.position))
        self.commit_entries()

    def drag_trim(self, trim, bound):
        self.update_trim(trim)
        self.seek(trim.start if bound == 'start' else trim.end)

    def reset_trim(self):
        self.update_trim(TrimRange(0, self.media.duration))
        self.seek(0)

    def toggle_play(self):
        if self.playing:
            self.stop_play()
            return
        if not self.commit_entries():
            return
        self.playing = True
        self.play_started = time.monotonic()
        self.position = self.trim.start
        self.play_button.configure(text='■  STOP PREVIEW')
        self.update_timeline()
        self.request_frame()

    def stop_play(self):
        self.playing = False
        self.play_button.configure(text='▶  PREVIEW TRIM')
        if self._play_id:
            self.after_cancel(self._play_id)
            self._play_id = None

    def next_frame(self):
        self._play_id = None
        if self.playing:
            self.position = min(self.trim.end, self.trim.start + time.monotonic() - self.play_started)
            self.update_timeline()
            if self.position >= self.trim.end:
                self.stop_play()
            self.request_frame()

    def export(self):
        if not self.commit_entries():
            return
        self.stop_play()
        try:
            self.exporter.start(self.media, self.trim, self.output_folder, self.edits)
            self.set_busy(True)
            self.progress['value'] = 0
            self.note.configure(text='Exporting your video…', fg=t.CYAN)
        except Exception as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def set_busy(self, busy):
        for widget in self.controls:
            widget.configure(state='disabled' if busy else 'normal')
        self.timeline.enabled = not busy
        self.video.enabled = not busy
        self.video.drag = None
        self.video.gesture = self.video.candidate = None
        self.update_brand_controls()
        self.play_button.configure(state='disabled' if busy else 'normal')
        self.export_button.configure(state='disabled' if busy else 'normal',
                                     text='EXPORTING…' if busy else 'EXPORT VIDEO  ↗')
        if busy:
            self.cancel_button.configure(state='normal')
            self.cancel_button.pack(side='left', padx=(10, 0))
        else:
            self.cancel_button.pack_forget()

    def cancel_export(self):
        self.exporter.cancel()
        self.cancel_button.configure(state='disabled')
        self.note.configure(text='Cancelling export…', fg=t.MUTED)

    def change_folder(self):
        chosen = filedialog.askdirectory(parent=self, initialdir=self.output_folder, title='Save exported videos here')
        if chosen:
            self.output_folder = Path(chosen)
            self.destination.configure(text='Save new copy in: ' + self.output_folder.name)

    def open_folder(self):
        try:
            folder = self.last_export.parent if self.last_export else self.output_folder
            os.startfile(str(folder))
        except OSError as exc:
            self.note.configure(text=f'Could not open folder: {exc}', fg=t.RED)

    def poll(self):
        self._poll_id = None
        if self.closed:
            return
        try:
            media, error = self.metadata.get_nowait()
            if error:
                self.note.configure(text=error, fg=t.RED)
                self.video.itemconfigure('placeholder', text='Video unavailable')
            elif not self.closing:
                self.media = media
                self.video.media = media
                self.preview_note.configure(text='Silent preview · Audio kept on export' if media.has_audio
                                            else 'Silent preview · No audio in source')
                self.preview = Preview(self.backend.ffmpeg, media)
                self.update_trim(TrimRange(0, media.duration))
                self.set_busy(False)
                self.request_frame()
        except Empty:
            pass
        if self.preview:
            try:
                frame = self.preview.frames.get_nowait()
                if frame.token == self.token:
                    if frame.error:
                        self.stop_play()
                        self.video.delete('frame', 'crop', 'privacy')
                        self.video.photo = None
                        self.video.source_view = False
                        self.video.itemconfigure('placeholder', text='Preview unavailable')
                        self.note.configure(text=frame.error, fg=t.RED)
                    else:
                        self._photo = tk.PhotoImage(master=self, data=frame.ppm, format='PPM')
                        self.video.itemconfigure('placeholder', text='')
                        self.video.show_frame(self._photo, frame.source_view, frame.edits)
                        if self.playing:
                            self._play_id = self.after(60, self.next_frame)
            except Empty:
                pass
        try:
            while True:
                event = self.exporter.events.get_nowait()
                self.progress['value'] = event.progress
                if event.kind in ('progress', 'validating'):
                    self.note.configure(text=event.message or f'Exporting… {round(event.progress*100)}%', fg=t.CYAN)
                else:
                    self.set_busy(False)
                    if event.kind == 'saved':
                        self.last_export = event.path
                        self.note.configure(text=f'EXPORTED ✓  {event.path.name}', fg=t.GREEN)
                    else:
                        self.note.configure(text=event.message, fg=t.RED if event.kind == 'error' else t.MUTED)
        except Empty:
            pass
        if self.closing and not self.exporter.busy:
            self.finish_close()
            return
        self._poll_id = self.after(60, self.poll)

    def close(self):
        if self.closed:
            return
        self.closing = True
        self.stop_play()
        if self.preview:
            self.preview.close()
        if self.exporter.busy:
            self.cancel_export()
        else:
            self.finish_close()

    def finish_close(self):
        if self.closed:
            return
        self.closed = True
        if self.preview:
            self.preview.close()
        for timer in (self._seek_id, self._poll_id, self._play_id):
            if timer:
                self.after_cancel(timer)
        self.destroy()
        if self.on_close:
            self.on_close(self)
