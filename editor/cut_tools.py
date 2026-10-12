"""Compact CUT panel for non-destructive section removal."""
import tkinter as tk
from tkinter import ttk

from ui import theme as t
from .cuts import CutRange
from .models import format_time


class CutTools:
    def __init__(self, window):
        self.window = window
        self.start = None
        self.end = None
        self.history = []
        self.items = []

        panel = window.panels['CUT']

        marks = tk.Frame(panel, bg=t.PANEL)
        marks.pack(fill='x', pady=(0, 6))

        start_group = tk.Frame(marks, bg=t.PANEL)
        start_group.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.start_label = t.label(start_group, 'CUT START  —', 8, t.MUTED, True, anchor='w')
        self.start_label.pack(fill='x')
        self.start_button = t.button(start_group, 'SET START', lambda: self.set_mark('start'))
        self.start_button.configure(pady=4, font=(t.FONT, -10, 'bold'))
        self.start_button.pack(fill='x', pady=(2, 0))

        end_group = tk.Frame(marks, bg=t.PANEL)
        end_group.pack(side='left', fill='x', expand=True, padx=(0, 8))
        self.end_label = t.label(end_group, 'CUT END  —', 8, t.MUTED, True, anchor='w')
        self.end_label.pack(fill='x')
        self.end_button = t.button(end_group, 'SET END', lambda: self.set_mark('end'))
        self.end_button.configure(pady=4, font=(t.FONT, -10, 'bold'))
        self.end_button.pack(fill='x', pady=(2, 0))

        self.remove_button = t.button(marks, 'REMOVE SECTION', self.remove_section, accent=True)
        self.remove_button.configure(pady=7, font=(t.FONT, -10, 'bold'))
        self.remove_button.pack(side='right', fill='y')

        lower = tk.Frame(panel, bg=t.PANEL)
        lower.pack(fill='both', expand=True)
        self.listbox = tk.Listbox(
            lower, height=2, activestyle='none', exportselection=False,
            bg=t.CONTROL, fg=t.TEXT, selectbackground=t.CYAN, selectforeground=t.BG,
            disabledforeground=t.MUTED, relief='flat', bd=0, highlightthickness=0,
            font=(t.MONO, -11),
        )
        self.listbox.pack(side='left', fill='both', expand=True)
        self.listbox.bind('<<ListboxSelect>>', self.selection_changed)
        scroll = ttk.Scrollbar(lower, orient='vertical', command=self.listbox.yview)
        scroll.pack(side='left', fill='y', padx=(3, 0))
        self.listbox.configure(yscrollcommand=scroll.set)

        actions = tk.Frame(lower, bg=t.PANEL)
        actions.pack(side='right', padx=(8, 0), fill='y')
        self.restore_button = t.button(actions, 'RESTORE', self.restore_selected)
        self.restore_button.configure(pady=3, font=(t.FONT, -10, 'bold'))
        self.restore_button.pack(fill='x')
        self.undo_button = t.button(actions, 'UNDO LAST', self.undo_last)
        self.undo_button.configure(pady=3, font=(t.FONT, -10, 'bold'))
        self.undo_button.pack(fill='x', pady=(4, 0))

        self.summary = t.label(panel, 'No sections removed.', 8, t.MUTED, anchor='w')
        self.summary.pack(fill='x', pady=(4, 0))

        window.controls.extend((
            self.start_button, self.end_button, self.remove_button,
            self.listbox, self.restore_button, self.undo_button,
        ))
        self.refresh()

    def draft(self):
        return self.start, self.end

    def set_mark(self, which):
        w = self.window
        if not w.media or not w.trim or w.exporter.busy or w.closing:
            return
        w.stop_play()
        value = max(w.trim.start, min(w.position, w.trim.end))
        if which == 'start':
            self.start = value
        else:
            self.end = value
        self.refresh()
        w.update_timeline()
        w.note.configure(
            text='Set the other cut marker, then choose REMOVE SECTION.',
            fg=t.MUTED,
        )

    def remove_section(self):
        w = self.window
        if self.start is None or self.end is None or not w.media or not w.trim:
            return
        w.stop_play()
        try:
            if self.start < w.trim.start - .0005 or self.end > w.trim.end + .0005:
                raise ValueError('Keep Cut Start and Cut End inside the current Trim selection.')
            cut = CutRange(self.start, self.end)
            plan = w.cuts.add(cut, w.media)
            plan.validate_selection(w.media, w.trim)
            w.cuts = plan
            self.history.append(cut)
            # Show the first frame that remains after the newly removed section.
            w.position = w.cuts.snap_position(cut.start, w.trim)
            self.start = self.end = None
            self.refresh(select=cut)
            w.cuts_changed(
                f'Removed {format_time(cut.start)} → {format_time(cut.end)}. '
                'Your original video is unchanged.'
            )
        except ValueError as exc:
            w.note.configure(text=str(exc), fg=t.RED)
            self.refresh()

    def restore_selected(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(self.items):
            return
        cut = self.items[index]
        self._restore(cut, 'Restored selected section.')

    def undo_last(self):
        w = self.window
        while self.history and self.history[-1] not in w.cuts.ranges:
            self.history.pop()
        if not self.history:
            return
        cut = self.history.pop()
        self._restore(cut, 'Undid the last removed section.')

    def _restore(self, cut, message):
        w = self.window
        w.stop_play()
        try:
            w.cuts = w.cuts.remove(cut)
        except ValueError as exc:
            w.note.configure(text=str(exc), fg=t.RED)
            self.refresh()
            return
        self.history = [item for item in self.history if item != cut]
        if w.trim:
            w.position = max(w.trim.start, min(cut.start, w.trim.end))
        self.refresh()
        w.cuts_changed(message)

    def selection_changed(self, _=None):
        self._update_states()

    def refresh(self, select=None):
        w = self.window
        if w.trim:
            if self.start is not None and not (w.trim.start <= self.start <= w.trim.end):
                self.start = None
            if self.end is not None and not (w.trim.start <= self.end <= w.trim.end):
                self.end = None
        previous = None
        selection = self.listbox.curselection()
        if selection and selection[0] < len(self.items):
            previous = self.items[selection[0]]

        self.items = list(w.cuts.ranges)
        self.listbox.configure(state='normal')
        self.listbox.delete(0, 'end')
        for index, cut in enumerate(self.items, 1):
            self.listbox.insert(
                'end',
                f'{index:02d}  {format_time(cut.start)}  →  {format_time(cut.end)}'
            )

        wanted = select if select in self.items else previous
        if wanted in self.items:
            index = self.items.index(wanted)
            self.listbox.selection_set(index)
            self.listbox.see(index)

        self.start_label.configure(
            text='CUT START  ' + (format_time(self.start) if self.start is not None else '—')
        )
        self.end_label.configure(
            text='CUT END  ' + (format_time(self.end) if self.end is not None else '—')
        )

        if w.media and w.trim:
            removed = w.cuts.removed_duration(w.trim)
            kept = w.cuts.kept_duration(w.trim)
            if removed > .0005:
                self.summary.configure(
                    text=f'{len(w.cuts.visible_ranges(w.trim))} removed · '
                         f'{format_time(removed)} cut · {format_time(kept)} kept'
                )
            else:
                self.summary.configure(text='No sections removed from the current Trim selection.')
        else:
            self.summary.configure(text='No sections removed.')

        self._update_states()

    def _update_states(self):
        w = self.window
        ready = bool(w.media and w.trim and not w.exporter.busy and not w.closing)
        self.listbox.configure(state='normal' if ready else 'disabled')
        self.start_button.configure(state='normal' if ready else 'disabled')
        self.end_button.configure(state='normal' if ready else 'disabled')
        valid_marks = ready and self.start is not None and self.end is not None and self.end > self.start
        self.remove_button.configure(state='normal' if valid_marks else 'disabled')
        selected = bool(self.listbox.curselection())
        self.restore_button.configure(state='normal' if ready and selected else 'disabled')
        undoable = any(item in w.cuts.ranges for item in self.history)
        self.undo_button.configure(state='normal' if ready and undoable else 'disabled')
