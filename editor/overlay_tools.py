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
            segments = window.add_segments(group, var, choices, self.size_changed if var is self.text_size else self.text_changed)
            for _, button in segments.buttons:
                button.configure(padx=7, pady=4)
        footer = tk.Frame(panel, bg=t.PANEL)
        footer.pack(fill='x')
        t.label(footer, 'Whole clip · 3 lines / 160 characters', 9, t.MUTED).pack(side='left')
        self.caption_button = t.button(footer, 'TIMED CAPTIONS', self.edit_captions)
        self.caption_button.configure(pady=1, font=(t.FONT, -9, 'bold'))
        self.caption_button.pack(side='right')
        window.controls.append(self.caption_button)
        self.style_button = t.button(footer, 'FONT & STYLE', self.edit_style)
        self.style_button.configure(pady=1,font=(t.FONT,-9,'bold'))
        self.style_button.pack(side='right',padx=8);window.controls.append(self.style_button)
        super().__init__(window)

    def edit_style(self):
        from .text_style_dialog import TextStyleDialog
        if self.window.media and not self.window.exporter.busy:
            for child in self.window.winfo_children():
                if isinstance(child,TextStyleDialog):child.lift();return
            TextStyleDialog(self.window)

    def size_changed(self):
        text=self.window.edits.text
        if text.style is not None:
            text=replace(text,style=replace(text.style,font_size=round(TEXT_SIZES[self.text_size.get()]*1080)))
            self.window.edits=replace(self.window.edits,text=text)
        self.text_changed()

    def text_modified(self, _=None):
        if self.input.edit_modified():
            self.input.edit_modified(False)
            self.text_changed()

    def commit_text(self):
        w = self.window
        w.edits = replace(w.edits, text=replace(w.edits.text, enabled=self.text_on.get(),
                         text=self.input.get('1.0', 'end-1c'), size=self.text_size.get(),
                         position=self.text_position.get()))

    def edit_captions(self):
        from .caption_tools import CaptionDialog
        if not self.window.exporter.busy:
            CaptionDialog(self.window)

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
