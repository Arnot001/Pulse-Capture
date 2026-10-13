"""Focused Text and Privacy panels; recorder UI has no overlay state."""
from dataclasses import replace
import tkinter as tk
from ui import theme as t
from .text_overlay import TextOverlay, TEXT_SIZES, TEXT_POSITIONS
from .privacy_tools import PrivacyTools


class OverlayTools(PrivacyTools):
    def __init__(self, window):
        self.window = window
        self.text_on = tk.BooleanVar(value=False)
        self.text_size = tk.StringVar(value='Medium')
        self.text_position = tk.StringVar(value='Bottom')
        panel = window.panels['TEXT']
        self.input = tk.Text(panel, height=2, wrap='word', bg=t.CONTROL, fg=t.TEXT,
                             insertbackground=t.CYAN, relief='flat', font=(t.FONT, -13),
                             padx=6, pady=3, undo=True)
        self.input.pack(fill='x', pady=(0, 5))
        self.input.bind('<<Modified>>', self.text_modified)
        window.controls.append(self.input)
        row = tk.Frame(panel, bg=t.PANEL)
        row.pack(fill='x')
        for var, choices in ((self.text_on, [(False, 'OFF'), (True, 'ON')]),
                             (self.text_size, [(v, v) for v in TEXT_SIZES]),
                             (self.text_position, [(v, v) for v in TEXT_POSITIONS])):
            group = tk.Frame(row, bg=t.PANEL)
            group.pack(side='left', fill='x', expand=True, padx=(0, 6))
            segments = window.add_segments(group, var, choices, self.text_changed)
            for _, button in segments.buttons:
                button.configure(padx=7, pady=4)
        t.label(panel, 'Whole clip · Up to 3 lines / 160 characters · Long lines shrink to fit',
                9, t.MUTED).pack(anchor='w')
        super().__init__(window)

    def text_modified(self, _=None):
        if self.input.edit_modified():
            self.input.edit_modified(False)
            self.text_changed()

    def commit_text(self):
        w = self.window
        w.edits = replace(w.edits, text=TextOverlay(self.text_on.get(), self.input.get('1.0', 'end-1c'),
                                                  self.text_size.get(), self.text_position.get()))

    def text_changed(self):
        w = self.window
        if w.exporter.busy or w.closing:
            return
        self.commit_text()
        if not w.media:
            return
        w.stop_play()
        if w.commit_entries():
            w.request_frame()
        else:
            # Never leave an old rendered caption looking like the current input.
            w.token += 1
            w.video.delete('frame', 'privacy', 'privacy-active', 'crop', 'zoom')
            w.video.photo = None
            w.video.itemconfigure('placeholder', text='Adjust your text to continue')
