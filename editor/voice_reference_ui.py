"""Explicit local reference import, separate from prebuilt embedding manifests."""
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import ttk

from ui import theme as t
from .voice_reference import PERMISSIONS, PRESENTATIONS, prepare_reference, reference_labels


class ReferenceVoiceDialog(tk.Toplevel):
    def __init__(self, panel, path):
        super().__init__(panel)
        self.panel = panel
        self.reference = None
        self.cancel = threading.Event()
        self.events = Queue()
        self.result_lock = threading.RLock()
        self.busy = True
        self.closing = False
        self.title('Add reference voice · local only')
        self.configure(bg=t.BG)
        self.geometry('660x650')
        self.transient(panel.winfo_toplevel())
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Destroy>', self.destroyed)
        self.grab_set()
        t.label(self, 'ADD REFERENCE VOICE', 15, t.CYAN).pack(anchor='w', padx=16, pady=12)
        self.info = t.label(self, 'Checking a private copy of the selected audio…', 10, t.MUTED,
                            wraplength=620, justify='left')
        self.info.pack(fill='x', padx=16, pady=6)
        t.label(self, 'Use clean speech from one speaker, without music. 10–30 seconds is recommended.\n'
                'Labels below are your descriptions, not verified identity or accent guarantees.',
                10, t.MUTED, wraplength=620, justify='left').pack(fill='x', padx=16, pady=8)
        form = tk.Frame(self, bg=t.BG)
        form.pack(fill='x', padx=16)
        self.values = {}
        for row, (key, label, default, choices) in enumerate([
            ('name', 'Display name', '', None),
            ('presentation', 'Voice presentation', 'Unspecified', PRESENTATIONS),
            ('style', 'Character / vocal style', 'Natural', None),
            ('language', 'Language', 'Unspecified', None),
            ('accent', 'Accent (if known)', 'Unspecified', None),
            ('permission', 'Permission', '', ('',)+PERMISSIONS),
            ('provenance', 'Source / consent / licence details', '', None)]):
            t.label(form, label, 10).grid(row=row, column=0, sticky='w', pady=7)
            variable = tk.StringVar(value=default)
            self.values[key] = variable
            if choices:
                widget = ttk.Combobox(form, textvariable=variable, values=choices, state='readonly')
            else:
                widget = tk.Entry(form, textvariable=variable, bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN)
            widget.grid(row=row, column=1, sticky='ew', padx=(10, 0), pady=7)
        form.columnconfigure(1, weight=1)
        self.consent = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text='I have the rights or speaker consent to create and reuse this voice.',
                       variable=self.consent, bg=t.BG, fg=t.TEXT, selectcolor=t.CONTROL,
                       wraplength=610, justify='left').pack(anchor='w', padx=16, pady=12)
        t.label(self, 'The reference, permission record and voice embedding stay in your local voice library.\n'
                'The original file is unchanged. No audio upload or paid request.',
                9, t.MUTED, wraplength=620, justify='left').pack(fill='x', padx=16)
        self.status = t.label(self, '', 10, t.MUTED, wraplength=620, justify='left')
        self.status.pack(fill='x', padx=16, pady=10)
        row = tk.Frame(self, bg=t.BG)
        row.pack(fill='x', padx=16)
        self.extract_button = t.button(row, 'CREATE LOCAL VOICE', self.create, accent=True)
        self.extract_button.pack(side='left')
        self.extract_button.configure(state='disabled')
        t.button(row, 'CANCEL', self.close).pack(side='right')
        ffmpeg = panel.ffmpeg()
        self.launch(lambda: prepare_reference(path, ffmpeg, self.cancel), 'prepared')
        self.timer = self.after(80, self.poll)

    def launch(self, work, kind):
        self.busy = True
        def worker():
            try:
                result = work()
                with self.result_lock:
                    if kind == 'prepared' and self.cancel.is_set():
                        result.close()
                        raise ValueError('Reference import cancelled.')
                    self.events.put((kind, result))
            except Exception as exc:
                self.events.put(('error', str(exc)))
            finally:
                if self.cancel.is_set() and self.reference:
                    self.reference.close()
        threading.Thread(target=worker, daemon=True).start()

    def create(self):
        if self.busy or self.reference is None:
            return
        try:
            labels = reference_labels(dict({key:value.get() for key,value in self.values.items()},
                                            consent=self.consent.get()))
        except ValueError as exc:
            self.status.configure(text=str(exc), fg=t.RED)
            return
        self.extract_button.configure(state='disabled')
        self.status.configure(text='Extracting the voice locally… CANCEL keeps your original unchanged.', fg=t.CYAN)
        self.launch(lambda: self.panel.catalogue.add_reference(self.reference, labels, self.cancel), 'voice')

    def poll(self):
        try:
            kind, value = self.events.get_nowait()
            self.busy = False
            if kind == 'prepared':
                self.reference = value
                self.info.configure(text=f'{value.source_name}\n{value.info["duration"]:.2f} seconds · '
                    f'{value.info["active_seconds"]:.2f}s audible audio · private copy ready')
                self.extract_button.configure(state='normal')
            elif kind == 'voice':
                self.panel.reference_added(value)
                self.closing = True
            else:
                self.status.configure(text=value, fg=t.RED)
                if self.reference:
                    self.extract_button.configure(state='normal')
        except Empty:
            pass
        if self.closing and not self.busy:
            self.finish()
            return
        self.timer = self.after(80, self.poll)

    def close(self):
        self.cancel.set()
        self.closing = True
        if self.busy:
            self.status.configure(text='Cancelling local work…', fg=t.MUTED)
        else:
            self.after_cancel(self.timer)
            self.finish()

    def finish(self):
        if self.reference:
            self.reference.close()
            self.reference = None
        self.panel.reference_dialog = None
        self.destroy()

    def destroyed(self, event):
        if event.widget is self:
            with self.result_lock:
                self.cancel.set()
                try:
                    while True:
                        kind, value = self.events.get_nowait()
                        if kind == 'prepared':
                            value.close()
                except Empty:
                    pass
            if hasattr(self, 'timer'):
                self.after_cancel(self.timer)
            if not self.busy and self.reference:
                self.reference.close()
