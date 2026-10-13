"""Compact source-time privacy list and independent editable draft."""
from dataclasses import replace
import tkinter as tk
from tkinter import ttk
from ui import theme as t
from .models import format_time, parse_time
from .privacy import Privacy, PrivacyMask, MODES, output_mask


class PrivacyTools:
    def __init__(self, window):
        self.window = window
        self.selected = None
        self.draft_rect = None
        self.privacy_mode = tk.StringVar(value='Blur')
        self.privacy_start = tk.StringVar(value='0:00.000')
        self.privacy_end = tk.StringVar(value='0:00.000')
        self._initialized = False
        self._listing = None
        panel = window.panels['PRIVACY']
        panel.columnconfigure(0, weight=1, uniform='privacy')
        panel.columnconfigure(1, weight=1, uniform='privacy')
        left = tk.Frame(panel, bg=t.PANEL)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        right = tk.Frame(panel, bg=t.PANEL)
        right.grid(row=0, column=1, sticky='nsew')
        def button(parent, label, action):
            b = t.button(parent, label, action, font=(t.FONT, -11, 'bold'))
            b.configure(padx=6, pady=2)
            window.controls.append(b)
            return b
        row = tk.Frame(left, bg=t.PANEL)
        row.pack(fill='x')
        group = t.Segments(row, self.privacy_mode, [(v,v.upper()) for v in MODES], self.mode_changed)
        group.pack(side='left', fill='x', expand=True)
        for _, b in group.buttons:
            b.configure(padx=6, pady=2, font=(t.FONT, -11, 'bold'))
            window.controls.append(b)
        self.new_button = button(row, 'NEW', self.new_mask)
        self.new_button.pack(side='right', padx=(5,0))
        for label, variable, bound in (('START', self.privacy_start, 'start'), ('END', self.privacy_end, 'end')):
            row = tk.Frame(left, bg=t.PANEL)
            row.pack(fill='x', pady=(3,0))
            t.label(row, label, 8, t.MUTED, True, width=6).pack(side='left')
            entry = tk.Entry(row, textvariable=variable, width=10, font=(t.MONO,-12),
                             bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN, relief='flat',
                             disabledbackground=t.CONTROL)
            entry.pack(side='left', fill='x', expand=True, ipady=2)
            entry.bind('<Return>', self.draft_changed)
            entry.bind('<FocusOut>', self.draft_changed)
            window.controls.append(entry)
            button(row, 'USE PLAYHEAD', lambda b=bound:self.privacy_use_playhead(b)).pack(side='right', padx=(5,0))
        row = tk.Frame(left, bg=t.PANEL)
        row.pack(fill='x', pady=(3,0))
        self.add_button = button(row, 'ADD PRIVACY MASK', self.add_mask)
        self.add_button.pack(side='left', fill='x', expand=True)
        self.update_button = button(row, 'UPDATE', self.update_mask)
        self.update_button.pack(side='left', padx=(5,0))
        listing = tk.Frame(right, bg=t.PANEL)
        listing.pack(fill='x')
        self.mask_list = tk.Listbox(listing, height=3, width=20, font=(t.MONO,-11),
                                   bg=t.CONTROL, fg=t.TEXT, selectbackground='#17464f',
                                   selectforeground=t.CYAN, relief='flat', highlightthickness=0,
                                   exportselection=False)
        scroll = ttk.Scrollbar(listing, orient='vertical', command=self.mask_list.yview)
        self.mask_list.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y')
        self.mask_list.pack(side='left',fill='x',expand=True)
        self.mask_list.bind('<<ListboxSelect>>', self.select_mask)
        window.controls.append(self.mask_list)
        row = tk.Frame(right, bg=t.PANEL)
        row.pack(fill='x',pady=(3,0))
        self.remove_button = button(row,'REMOVE',self.remove_mask)
        self.remove_button.pack(side='left')
        self.clear_button = button(row,'CLEAR ALL',self.clear_masks)
        self.clear_button.pack(side='left',padx=(5,0))
        self.privacy_hint = t.label(right,'Draw a box, set source times, then Add.',8,t.MUTED,anchor='w')
        self.privacy_hint.pack(fill='x',pady=(3,0))

    def ready(self):
        w = self.window
        return bool(w.media and w.video.enabled and not w.exporter.busy and not w.closing)

    def draft_time(self, text, bound):
        # Formatting to milliseconds must not move an unchanged stored boundary
        # or make a rounded end extend beyond the file.
        w = self.window
        candidates = []
        if self.selected is not None:
            candidates.append(getattr(w.edits.privacy.masks[self.selected], bound))
        candidates.extend((getattr(w.trim, bound), w.media.duration))
        for value in candidates:
            if text == format_time(value):
                return value
        return parse_time(text)

    def draft_mask(self):
        w = self.window
        mask = PrivacyMask(self.privacy_mode.get(), self.draft_rect,
                           self.draft_time(self.privacy_start.get(), "start"),
                           self.draft_time(self.privacy_end.get(), "end"))
        mask.validate(w.media)
        return mask

    def dirty(self):
        if self.draft_rect is None:
            return False
        try:
            mask = self.draft_mask()
        except ValueError:
            return True
        masks = self.window.edits.privacy.masks
        return self.selected is None or self.selected >= len(masks) or masks[self.selected] != mask

    def privacy_committed(self):
        if self.dirty():
            self.window.note.configure(text='Privacy draft is not added yet. Choose ADD PRIVACY MASK or UPDATE; NEW discards the draft.',fg=t.RED)
            self.window.select_tool('PRIVACY')
            return False
        return True

    def new_mask(self):
        if not self.ready():
            return
        self.selected = None
        self.draft_rect = None
        self.privacy_start.set(format_time(self.window.trim.start))
        self.privacy_end.set(format_time(self.window.trim.end))
        self.draft_changed()

    def privacy_use_playhead(self, bound):
        if not self.ready():
            return
        self.window.stop_play()
        (self.privacy_start if bound=='start' else self.privacy_end).set(format_time(self.window.position))
        self.draft_changed()

    def mode_changed(self):
        self.draft_changed()

    def mask_changed(self, rect):
        if not self.ready():
            return
        self.draft_rect = rect
        self.draft_changed()

    def draft_changed(self, _=None):
        if not self.ready():
            return
        self.window.stop_play()
        self.refresh()
        self.window.request_frame()

    def preview_edits(self, edits):
        # Live draft feedback is confined to the Privacy tool; export uses saved masks.
        if self.draft_rect is None or not self.dirty():
            return edits
        try:
            mask = self.draft_mask()
        except ValueError:
            return edits
        masks = list(edits.privacy.masks)
        if self.selected is None:
            masks.append(mask)
        else:
            masks[self.selected] = mask
        return replace(edits,privacy=Privacy(tuple(masks)))

    def save_mask(self, update):
        if not self.ready() or (update and self.selected is None):
            return
        try:
            mask = self.draft_mask()
        except ValueError as exc:
            self.window.note.configure(text=str(exc),fg=t.RED)
            return
        masks = list(self.window.edits.privacy.masks)
        if update:
            masks[self.selected] = mask
        else:
            masks.append(mask)
            self.selected = len(masks)-1
        self.window.edits = replace(self.window.edits,privacy=Privacy(tuple(masks)))
        self.window.note.configure(text='Privacy mask updated.' if update else 'Privacy mask added. Choose NEW for another box.',fg=t.MUTED)
        self.draft_changed()

    def add_mask(self):
        self.save_mask(False)

    def update_mask(self):
        self.save_mask(True)

    def select_mask(self, _=None):
        if not self.ready() or not self.mask_list.curselection():
            return
        index = self.mask_list.curselection()[0]
        if index == self.selected:
            return
        self.selected = index
        mask = self.window.edits.privacy.masks[index]
        self.draft_rect = mask.rect
        self.privacy_mode.set(mask.mode)
        self.privacy_start.set(format_time(mask.start))
        self.privacy_end.set(format_time(mask.end))
        self.draft_changed()

    def remove_mask(self):
        if not self.ready() or self.selected is None:
            return
        masks = list(self.window.edits.privacy.masks)
        masks.pop(self.selected)
        self.window.edits = replace(self.window.edits,privacy=Privacy(tuple(masks)))
        self.new_mask()

    def clear_masks(self):
        if not self.ready():
            return
        self.window.edits = replace(self.window.edits,privacy=Privacy())
        self.new_mask()

    def refresh(self):
        w = self.window
        if not hasattr(w,'video'):
            return
        if w.media and not self._initialized:
            self.privacy_start.set(format_time(w.trim.start))
            self.privacy_end.set(format_time(w.trim.end))
            self._initialized = True
        masks = w.edits.privacy.masks
        ready = self.ready()
        if masks != self._listing:
            self.mask_list.configure(state='normal')
            self.mask_list.delete(0,'end')
            for i, mask in enumerate(masks):
                self.mask_list.insert('end',f'{i+1:02d} {mask.mode.upper():8} {format_time(mask.start)} → {format_time(mask.end)}')
            self._listing = masks
        self.mask_list.selection_clear(0,'end')
        if self.selected is not None and self.selected < len(masks):
            self.mask_list.selection_set(self.selected)
            self.mask_list.see(self.selected)
        self.mask_list.configure(state='normal' if ready else 'disabled')
        self.update_button.configure(state='normal' if ready and self.selected is not None else 'disabled')
        self.remove_button.configure(state='normal' if ready and self.selected is not None else 'disabled')
        self.clear_button.configure(state='normal' if ready and masks else 'disabled')
        w.video.privacy_active = w.tool.get()=='PRIVACY'
        w.video.mask = self.draft_rect
        w.video.mode = self.privacy_mode.get()
        w.video.selected_index = self.selected
        w.video.gesture = w.video.candidate = None
        if self.draft_rect and w.media and not output_mask(self.draft_rect,w.media,w.edits.crop):
            hint = 'Box outside crop · source position is kept.'
        elif self.dirty():
            hint = 'Draft preview · Add / Update to keep it.'
        elif self.selected is not None:
            hint = 'Source times · cyan box edits selection.'
        else:
            hint = 'Draw a box, set source times, then Add.'
        self.privacy_hint.configure(text=hint)
        if hasattr(w,'timeline'):
            w.timeline.privacy = w.edits.privacy
            w.timeline.draw()
        w.video.draw_overlay()
