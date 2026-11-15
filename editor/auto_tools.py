"""Quick Edit AUTO tab: local highlight scan with manual review before export."""
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ui import theme as t
from .auto_analysis import analyze_video
from .auto_plan import STYLES
from .cuts import CutPlan
from .models import TrimRange, format_time
from .transforms import SHORTS_FORMAT


class AutoTools:
    def __init__(self, window):
        self.window = window
        self.events = Queue()
        self.suggestions = ()
        self.worker = None
        self.busy = False
        self.cancel = threading.Event()
        self._closed = False
        self.batch = None
        self.batch_ok = 0
        panel = window.panels['AUTO']
        upper = tk.Frame(panel, bg=t.PANEL)
        upper.pack(fill='x')
        t.label(upper, 'STYLE', 9, t.MUTED).pack(side='left', padx=(0, 6))
        self.style = tk.StringVar(value=STYLES[0])
        self.style_picker = ttk.Combobox(upper, textvariable=self.style, width=18,
                                          values=STYLES, state='readonly')
        self.style_picker.pack(side='left', padx=(0, 12))
        t.label(upper, 'SHORTS', 9, t.MUTED).pack(side='left', padx=(0, 6))
        self.count = tk.StringVar(value='2')
        self.count_picker = ttk.Combobox(upper, textvariable=self.count, width=3,
                                          values=('1', '2', '3'), state='readonly')
        self.count_picker.pack(side='left', padx=(0, 12))
        self.scan_button = t.button(upper, '⚡ FIND HIGHLIGHTS', self.scan, accent=True)
        self.scan_button.configure(padx=10, pady=5)
        self.scan_button.pack(side='left')
        self.export_all_button = t.button(upper, 'EXPORT ALL', self.export_all)
        self.export_all_button.configure(padx=8, pady=5, state='disabled')
        self.export_all_button.pack(side='left', padx=(8, 0))

        picks = tk.Frame(panel, bg=t.PANEL)
        picks.pack(fill='x', pady=(8, 4))
        self.picks = []
        for index in range(3):
            button = t.button(picks, f'#{index+1} · --',
                              lambda n=index: self.apply(n))
            button.configure(font=(t.FONT, -10), padx=5, pady=4, state='disabled')
            button.pack(side='left', fill='x', expand=True, padx=(0, 6))
            self.picks.append(button)
        self.message = t.label(panel, 'Scan first. Review each suggested Short before exporting.',
                               9, t.MUTED)
        self.message.pack(anchor='w')

    def refresh(self):
        ready = bool(self.window.media and not self.window.exporter.busy
                     and not self.window.closing and not self._closed
                     and self.batch is None)
        self.scan_button.configure(state='normal' if ready and not self.busy else 'disabled')
        self.export_all_button.configure(
            state='normal' if ready and not self.busy and self.suggestions else 'disabled')
        for n, button in enumerate(self.picks):
            button.configure(state='normal' if ready and n < len(self.suggestions) else 'disabled')
        self.style_picker.configure(state='readonly' if ready and not self.busy else 'disabled')
        self.count_picker.configure(state='readonly' if ready and not self.busy else 'disabled')

    def scan(self):
        w = self.window
        if not w.media or w.exporter.busy or w.closing or self.busy:
            return
        self.suggestions = ()
        self.busy = True
        self.cancel.clear()
        media, ffmpeg = w.media, w.backend.ffmpeg
        style, count = self.style.get(), int(self.count.get())
        self.message.configure(text='Scanning local scenes and sound…', fg=t.CYAN)
        self.refresh()

        def work():
            try:
                results, details = analyze_video(ffmpeg, media, style=style, count=count,
                                                 cancel_event=self.cancel)
                self.events.put((results, details, None))
            except Exception as exc:
                self.events.put(((), '', str(exc)))

        self.worker = threading.Thread(target=work, name='Pulse automatic highlight scan',
                                       daemon=True)
        self.worker.start()

    def poll(self):
        if self._closed:
            return
        try:
            while True:
                clips, details, error = self.events.get_nowait()
                self.busy = False
                self.suggestions = clips
                if error:
                    self.message.configure(text='Auto scan failed: ' + error[:160], fg=t.RED)
                else:
                    self.message.configure(
                        text=details + ' · Review and click a suggestion to load it.',
                        fg=t.MUTED)
                for n, button in enumerate(self.picks):
                    if n < len(clips):
                        clip = clips[n]
                        button.configure(text=f'#{n+1}  {format_time(clip.start)}–{format_time(clip.end)}')
                    else:
                        button.configure(text=f'#{n+1} · --')
                self.refresh()
        except Empty:
            pass

    def apply(self, index, *, confirm=True):
        w = self.window
        if (not w.media or w.exporter.busy or w.closing
                or index >= len(self.suggestions)):
            return False
        clip = self.suggestions[index]
        # Do not erase user cuts or animated crop keys without permission.
        if confirm and (w.cuts.ranges or w.edits.crop_motion.keyframes) and not messagebox.askyesno(
                'Replace cuts / crop keys?',
                'This Short needs a new time range and a clean cut plan. '
                'Reset existing cuts and crop keyframes for this suggestion?', parent=w):
            return False
        try:
            candidate = w.edits.with_format(w.media, SHORTS_FORMAT)
            candidate.validate(w.media)
            selection = TrimRange(clip.start, clip.end)
            selection.validate(w.media)
            w.stop_play()
            w.cuts = CutPlan()
            w.edits = candidate
            w.format_choice.set(SHORTS_FORMAT)
            w.video.crop = candidate.crop
            w.update_trim(selection)
            w.position = clip.start
            w.overlay_tools.refresh()
            w.polish_tools.refresh()
            w.update_timeline()
            w.request_frame()
            w.note.configure(
                text=f'Auto #{index+1}: {clip.reason}. Adjust crop/captions, then EXPORT VIDEO.',
                fg=t.CYAN)
            return True
        except ValueError as exc:
            w.note.configure(text='Auto suggestion could not be applied: ' + str(exc), fg=t.RED)
            return False

    def export_all(self):
        """Use Quick Edit's existing non-overwriting exporter for each suggestion."""
        w = self.window
        if (not self.suggestions or self.batch is not None or self.busy
                or w.exporter.busy or w.closing):
            return
        approved = messagebox.askyesno(
            'Export suggested Shorts?',
            f'Export {len(self.suggestions)} suggested 9:16 Short(s) using the '
            'current edit effects and centered crops? Review each result before '
            'posting. Any current cuts/crop keys will be reset for each clip.',
            parent=w)
        if not approved:
            return
        self.batch = list(range(len(self.suggestions)))
        self.batch_ok = 0
        self.refresh()
        self._export_next()

    def _export_next(self):
        if self._closed or self.batch is None:
            return
        if not self.batch:
            self.batch = None
            self.message.configure(
                text=f'Exported {self.batch_ok} suggested Short(s). Review each MP4 before posting.',
                fg=t.CYAN)
            self.refresh()
            return
        index = self.batch.pop(0)
        if not self.apply(index, confirm=False):
            self.batch = None
            self.message.configure(text='Auto batch stopped: could not prepare clip.', fg=t.RED)
            self.refresh()
            return
        self.message.configure(
            text=f'Exporting Short {index+1}/{len(self.suggestions)}…',
            fg=t.CYAN)
        self.window.export()
        if not self.window.exporter.busy:
            self.batch = None
            self.message.configure(text='Auto batch stopped: export could not start.', fg=t.RED)
            self.refresh()

    def export_completed(self, event):
        if self.batch is None or self._closed:
            return
        if event.kind == 'saved':
            self.batch_ok += 1
            self.window.after(0, self._export_next)
        else:
            self.batch = None
            self.message.configure(
                text=f'Auto batch stopped after {self.batch_ok} export(s): {event.message}',
                fg=t.RED)
            self.refresh()

    def close(self):
        self._closed = True
        self.batch = None
        self.cancel.set()
