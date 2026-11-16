"""Import, inspect and revise a local Pulse recipe before opening Quick Edit."""
import json
from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from ui import theme as t
from .auto_analysis import AutoCancelled
from .auto_job import default_cache
from .auto_plan import validate_plan
from .pulse_plan import (parse_pulse_plan, source_identity, starter_plan,
                         timeline_positions, read_pulse_plan)


class PulsePlanDialog(tk.Toplevel):
    def __init__(self, window, plan=None, source_media=None):
        super().__init__(window)
        self.window = window
        self.media = source_media or window.media
        self.backend = window.backend
        self.closed = self.closing = self.busy = False
        self.events, self.cancel = Queue(), threading.Event()
        self.folder = None
        self.title('Pulse Capture · Pulse Edit Plan')
        self.geometry('880x740')
        self.minsize(700, 580)
        self.configure(bg=t.BG)
        self.protocol('WM_DELETE_WINDOW', self.close)
        t.label(self, 'PULSE EDIT PLAN', 20, t.CYAN, True).pack(anchor='w', padx=20, pady=(14, 5))
        t.label(self, self.media.path.name, 10, t.MUTED).pack(anchor='w', padx=20)
        t.label(self, 'Edit the JSON, validate, then render a preview. No API key required.\n'
                'Re-rendering starts a new edit from this recipe; Quick Edit changes stay with the previous version.\n'
                'Commentary is a script only. Unverified captions are withheld; jokes are not verified facts.',
                10, t.MUTED, justify='left').pack(anchor='w', padx=20, pady=8)
        notebook = ttk.Notebook(self)
        notebook.pack(fill='both', expand=True, padx=20, pady=6)
        json_panel = tk.Frame(notebook, bg=t.PANEL)
        notebook.add(json_panel, text='Edit JSON recipe')
        self.editor = tk.Text(json_panel, wrap='none', undo=True, font=(t.MONO, -12),
                              bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN)
        scroll = ttk.Scrollbar(json_panel, command=self.editor.yview)
        scroll.pack(side='right', fill='y')
        self.editor.configure(yscrollcommand=scroll.set)
        self.editor.pack(fill='both', expand=True)
        self.timeline = ttk.Treeview(notebook, columns=('time', 'kind', 'detail'), show='headings')
        for name, title, width in (('time', 'Output seconds', 140), ('kind', 'Element', 100), ('detail', 'Source / text / commentary', 540)):
            self.timeline.heading(name, text=title)
            self.timeline.column(name, width=width)
        notebook.add(self.timeline, text='Validated timeline')
        self.status = t.label(self, 'Ready to validate.', 10, t.MUTED, wraplength=820, justify='left')
        self.status.pack(anchor='w', padx=20, pady=8)
        row = tk.Frame(self, bg=t.BG)
        row.pack(fill='x', padx=20, pady=(0, 14))
        self.actions = []
        for label, command in (('VALIDATE', self.validate), ('SAVE PLAN AS', self.save),
                               ('RENDER PREVIEW', self.render)):
            button = t.button(row, label, command, accent=label == 'RENDER PREVIEW')
            button.pack(side='left', padx=(0, 8))
            self.actions.append(button)
        self.close_button = t.button(row, 'CLOSE', self.close)
        self.close_button.pack(side='right')
        self._poll = self.after(80, self.poll)
        if plan is None:
            self.status.configure(text='Computing source fingerprint for your starter plan…')
            self.work(lambda: starter_plan(self.media, source_identity(self.media, self.cancel)), 'template')
        else:
            self.set_plan(plan)

    def set_plan(self, plan):
        self.editor.delete('1.0', 'end')
        self.editor.insert('1.0', json.dumps(plan, ensure_ascii=False, indent=2))
        self.validate()

    def get_plan(self):
        plan = parse_pulse_plan(self.editor.get('1.0', 'end-1c'))
        validate_plan(plan, self.media)
        return plan

    def validate(self):
        try:
            plan = self.get_plan()
            for node in self.timeline.get_children():
                self.timeline.delete(node)
            positions = timeline_positions(plan)
            for item, (start, end) in zip(plan['timeline'], positions):
                detail = (f'{item["start"]:g} → {item["end"]:g}s at {item.get("speed", 1):g}×'
                          if item['kind'] == 'shot' else f'Freeze at {item["source_time"]:g}s'
                          if item['kind'] == 'freeze' else item['text'])
                if item.get('commentary'):
                    detail += ' · SCRIPT: '+item['commentary']
                self.timeline.insert('', 'end', values=(f'{start:.3f}–{end:.3f}', item['kind'], detail))
            for cue in plan['captions']:
                self.timeline.insert('', 'end', values=(f'{cue["start"]:.3f}–{cue["end"]:.3f}',
                                     cue['zone']+' caption', f'[{cue["basis"]}] {cue["text"]}'))
            withheld = sum(c['basis'] == 'unverified' for c in plan['captions'])
            self.status.configure(text=f'Valid recipe · {positions[-1][1]:.3f}s · '
                                  f'{len(plan["timeline"])} elements · {withheld} unverified captions withheld. '
                                  'Source fingerprint will be checked before rendering.', fg=t.GREEN)
            return plan
        except (ValueError, UnicodeError) as exc:
            self.status.configure(text=str(exc), fg=t.RED)
            return None

    def save(self):
        plan = self.validate()
        if plan is None:
            return
        chosen = filedialog.asksaveasfilename(parent=self, title='Save a new Pulse plan',
                     defaultextension='.json', filetypes=[('Pulse plan', '*.json')])
        if chosen:
            try:
                with Path(chosen).open('x', encoding='utf-8') as stream:
                    json.dump(plan, stream, ensure_ascii=False, indent=2)
                self.status.configure(text='Saved a new plan. Existing files are never replaced.', fg=t.GREEN)
            except OSError as exc:
                self.status.configure(text=f'Choose a new filename: {exc}', fg=t.RED)

    def work(self, function, kind):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        self.editor.configure(state='disabled')
        for button in self.actions:
            button.configure(state='disabled')
        self.close_button.configure(text='CANCEL')
        def run():
            try:
                self.events.put((kind, function()))
            except AutoCancelled as exc:
                self.events.put(('cancelled', str(exc)))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def render(self):
        if self.busy:
            return
        plan = self.validate()
        if plan is None:
            return
        from .pulse_job import assemble_plan
        self.work(lambda: (plan, assemble_plan(self.backend, self.media, plan,
                  default_cache()/'pulse-plans', self.cancel,
                  lambda message: self.events.put(('progress', message)))), 'rendered')

    def poll(self):
        self._poll = None
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'progress':
                    self.status.configure(text=value, fg=t.CYAN)
                    continue
                self.busy = False
                if self.closing:
                    continue
                self.editor.configure(state='normal')
                for button in self.actions:
                    button.configure(state='normal')
                self.close_button.configure(text='CLOSE')
                if kind == 'template':
                    self.set_plan(value)
                elif kind == 'rendered':
                    plan, (self.folder, media) = value
                    from .editor_window import EditorWindow
                    candidate = EditorWindow(self.window, media.path, self.backend,
                                 self.window.auto_children.discard, pulse_candidate=(plan, self.media))
                    self.window.auto_children.add(candidate)
                    candidate.output_folder = self.media.path.parent
                    candidate.destination.configure(text='New export beside your original recording')
                    candidate.lift()
                    self.status.configure(text='Preview opened in Quick Edit. Edit this recipe and render again to revise shots or titles.', fg=t.GREEN)
                else:
                    self.status.configure(text=value, fg=t.RED if kind == 'error' else t.MUTED)
        except Empty:
            pass
        if self.closing and not self.busy:
            self.finish_close()
        elif not self.closed:
            self._poll = self.after(80, self.poll)

    def close(self):
        self.closing = True
        self.cancel.set()
        if self.busy:
            self.status.configure(text='Cancelling and cleaning temporary assembly files…', fg=t.MUTED)
            self.close_button.configure(state='disabled')
        else:
            self.finish_close()

    def finish_close(self):
        if self.closed:
            return
        self.closed = True
        if self._poll:
            self.after_cancel(self._poll)
        self.window.auto_children.discard(self)
        self.destroy()


def open_plan_dialog(window, *, template=False, plan=None, media=None):
    if not template and plan is None:
        path = filedialog.askopenfilename(parent=window, title='Import Pulse Edit Plan',
                                         filetypes=[('Pulse plan JSON', '*.json')])
        if not path:
            return None
        plan = read_pulse_plan(path)
    dialog = PulsePlanDialog(window, plan, media)
    window.auto_children.add(dialog)
    return dialog
