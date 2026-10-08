"""Focused Text and Privacy panels; recorder UI has no overlay state."""
from dataclasses import replace
import tkinter as tk
from ui import theme as t
from .text_overlay import TextOverlay, TEXT_SIZES, TEXT_POSITIONS
from .privacy import Privacy, MODES, output_mask


class OverlayTools:
    def __init__(self, window):
        self.window = window
        self.text_on = tk.BooleanVar(value=False)
        self.text_size = tk.StringVar(value='Medium')
        self.text_position = tk.StringVar(value='Bottom')
        self.privacy_mode = tk.StringVar(value='Blur')
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
        panel = window.panels['PRIVACY']
        row = tk.Frame(panel, bg=t.PANEL)
        row.pack(fill='x')
        group = tk.Frame(row, bg=t.PANEL)
        group.pack(side='left', fill='x', expand=True, padx=(0, 14))
        window.add_segments(group, self.privacy_mode, [(v, v) for v in MODES], self.mode_changed)
        clear = t.button(row, 'CLEAR MASK', lambda: self.mask_changed(None))
        clear.pack(side='right', anchor='n')
        window.controls.append(clear)
        t.label(panel, 'Draw a box. Drag inside to move; drag a corner to resize.', 9, t.MUTED).pack(anchor='w')
        self.privacy_hint = t.label(panel, 'One fixed box for the whole clip. Check every part before sharing.', 9, t.MUTED)
        self.privacy_hint.pack(anchor='w', pady=(3, 0))

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
            w.video.delete('frame', 'privacy', 'crop')
            w.video.photo = None
            w.video.itemconfigure('placeholder', text='Adjust your text to continue')

    def mode_changed(self):
        self.mask_changed(self.window.edits.privacy.mask)

    def mask_changed(self, rect):
        w = self.window
        if w.exporter.busy or w.closing:
            return
        w.edits = replace(w.edits, privacy=Privacy(self.privacy_mode.get(), rect))
        w.stop_play()
        self.refresh()
        w.request_frame()

    def refresh(self):
        w = self.window
        if not hasattr(w, 'video'):
            return
        w.video.privacy_active = w.tool.get() == 'PRIVACY'
        w.video.mask = w.edits.privacy.mask
        w.video.mode = w.edits.privacy.mode
        w.video.gesture = w.video.candidate = None
        if w.media and w.edits.privacy.mask and not output_mask(w.edits.privacy.mask, w.media, w.edits.crop):
            message = 'Mask is outside this crop. It stays anchored to the source; draw here to replace it.'
        else:
            message = 'One fixed box for the whole clip. Check every part before sharing.'
        self.privacy_hint.configure(text=message)
        w.video.draw_overlay()
