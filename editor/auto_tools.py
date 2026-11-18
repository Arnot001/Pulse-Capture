"""One Auto Edit entry point; candidates open in the existing Quick Edit window."""
from dataclasses import asdict
import os
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import ttk

from ui import theme as t
from .auto_ai import Pricing
from .auto_analysis import AutoCancelled
from .auto_job import AutoJob
from .auto_plan import AutoOptions, STYLES
from .auto_selection import source_ranges


class AutoEditDialog(tk.Toplevel):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.title('Pulse Capture · Auto Edit')
        self.configure(bg=t.BG)
        self.geometry('700x650')
        self.minsize(660, 600)
        self.transient(window)
        self.busy = self.closed = self.closing = False
        self.events = Queue()
        self.cancel = threading.Event()
        self.job = None
        self.payload = None
        self.protocol('WM_DELETE_WINDOW', self.close)
        t.label(self, 'AUTO EDIT', 20, t.CYAN, True).pack(anchor='w', padx=22, pady=(18, 6))
        t.label(self, window.path.name, 10, t.MUTED, wraplength=640).pack(anchor='w', padx=22)
        options = tk.Frame(self, bg=t.BG)
        options.pack(fill='x', padx=22, pady=12)
        self.count, self.style = tk.StringVar(value='3'), tk.StringVar(value='News/Preview')
        self.minimum, self.maximum = tk.StringVar(value='20'), tk.StringVar(value='35')
        self.inputs = []
        for label, var, values in (('Shorts', self.count, ('1', '2', '3')), ('Style', self.style, STYLES)):
            t.label(options, label, 10).pack(side='left', padx=(0, 6))
            combo = ttk.Combobox(options, textvariable=var, values=values, state='readonly',
                                 width=3 if label == 'Shorts' else 15)
            combo.pack(side='left', padx=(0, 14))
            self.inputs.append(combo)
        for label, var in (('Min sec', self.minimum), ('Max sec', self.maximum)):
            t.label(options, label, 10).pack(side='left', padx=(0, 5))
            entry = tk.Entry(options, textvariable=var, width=4)
            entry.pack(side='left', padx=(0, 10))
            self.inputs.append(entry)
        self.key = tk.StringVar(value=os.environ.get('OPENAI_API_KEY', ''))
        keyrow = tk.Frame(self, bg=t.BG)
        keyrow.pack(fill='x', padx=22)
        t.label(keyrow, 'OpenAI key (optional)', 10).pack(side='left')
        self.key_entry = tk.Entry(keyrow, textvariable=self.key, show='•', width=35)
        self.key_entry.pack(side='left', fill='x', expand=True, padx=(12, 0))
        t.label(self, 'Key stays in this session. AI sends up to 18 sampled frames and the local transcript.\n'
                'Local-only editing sends nothing. All candidates need review before publishing.',
                9, t.MUTED, wraplength=650, justify='left').pack(anchor='w', padx=22, pady=7)
        self.pricing = Pricing()
        self.settings_button = t.button(self, 'MODEL & BUDGET SETTINGS', self.settings)
        self.settings_button.configure(pady=3, font=(t.FONT, -10, 'bold'))
        self.settings_button.pack(anchor='w', padx=22)
        import_row = tk.Frame(self, bg=t.BG)
        import_row.pack(fill='x', padx=22, pady=(10, 0))
        self.import_button = t.button(import_row, 'IMPORT PULSE PLAN', self.import_plan, accent=True)
        self.import_button.pack(side='left')
        self.template_button = t.button(import_row, 'NEW PLAN / SOURCE ID', lambda: self.import_plan(True))
        self.template_button.pack(side='left', padx=8)
        actions = tk.Frame(self, bg=t.BG)
        actions.pack(fill='x', padx=22, pady=12)
        self.analyse_button = t.button(actions, 'ANALYSE SOURCE', self.prepare, accent=True)
        self.analyse_button.pack(side='left')
        self.local_button = t.button(actions, 'CREATE LOCAL-ONLY', self.local)
        self.local_button.pack(side='left', padx=8)
        self.ai_button = t.button(actions, 'CREATE WITH AI', self.ai)
        self.ai_button.pack(side='left')
        self.local_button.configure(state='disabled')
        self.ai_button.configure(state='disabled')
        self.status = t.label(self, 'Choose settings, then analyse. Local processing is free.', 10, t.MUTED,
                              wraplength=650, justify='left', anchor='w')
        self.status.pack(fill='x', padx=22, pady=(0, 8))
        self.results = tk.Frame(self, bg=t.BG)
        self.results.pack(fill='both', expand=True, padx=22)
        footer = tk.Frame(self, bg=t.BG)
        footer.pack(fill='x', padx=22, pady=14)
        self.folder_button = t.button(footer, 'OPEN JOB FOLDER', self.open_folder)
        self.folder_button.pack(side='left')
        self.folder_button.configure(state='disabled')
        self.close_button = t.button(footer, 'CLOSE', self.close)
        self.close_button.pack(side='right')
        self._poll = self.after(80, self.poll)
        for var in (self.count, self.style, self.minimum, self.maximum):
            var.trace_add('write', self.invalidate)

    def import_plan(self, template=False):
        from .pulse_tools import open_plan_dialog
        try:
            open_plan_dialog(self.window, template=template)
        except (ValueError, OSError) as exc:
            self.status.configure(text=str(exc), fg=t.RED)

    def invalidate(self, *_):
        if not self.busy:
            self.job = None
            self.local_button.configure(state='disabled')
            self.ai_button.configure(state='disabled')
            self.status.configure(text='Options changed. Analyse again to refresh candidates and cost.', fg=t.MUTED)

    def settings(self):
        dialog = tk.Toplevel(self)
        dialog.title('Auto Edit model and GBP budget')
        dialog.configure(bg=t.BG)
        dialog.transient(self)
        dialog.grab_set()
        labels = {'model': 'Responses vision model', 'input_usd_per_million': 'Input USD / million tokens',
                  'output_usd_per_million': 'Output USD / million tokens', 'usd_to_gbp': 'USD → GBP (planning rate)',
                  'image_tokens_upper': 'Upper billable tokens / image', 'budget_gbp': 'Job cap GBP (maximum 0.50)'}
        variables = {}
        for row, (key, value) in enumerate(asdict(self.pricing).items()):
            t.label(dialog, labels[key], 10).grid(row=row, column=0, padx=16, pady=6, sticky='w')
            variables[key] = tk.StringVar(value=str(value))
            tk.Entry(dialog, textvariable=variables[key], width=34).grid(row=row, column=1, padx=16, pady=6)
        note = t.label(dialog, 'Rates checked 12 Nov 2026. Exchange rate is configurable, not a live quote.\n'
                       'For another model, verify its prices and image billing allowance first.',
                       9, t.MUTED, wraplength=540, justify='left')
        note.grid(row=6, column=0, columnspan=2, padx=16, pady=8)
        def save():
            try:
                values = {k: (v.get().strip() if k == 'model' else int(v.get()) if k == 'image_tokens_upper'
                              else float(v.get())) for k, v in variables.items()}
                pricing = Pricing(**values)
                pricing.validate()
                self.pricing = pricing
                self.job = None
                self.local_button.configure(state='disabled')
                self.ai_button.configure(state='disabled')
                self.status.configure(text='Settings updated. Analyse again to refresh the cost estimate.')
                dialog.destroy()
            except ValueError as exc:
                note.configure(text=str(exc), fg=t.RED)
        t.button(dialog, 'SAVE', save, accent=True).grid(row=7, column=0, columnspan=2, pady=12)

    def work(self, function, kind):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        for button in (self.analyse_button, self.local_button, self.ai_button, self.settings_button):
            button.configure(state='disabled')
        for widget in self.inputs:
            widget.configure(state='disabled')
        self.close_button.configure(text='CANCEL')
        def run():
            try:
                self.events.put((kind, function()))
            except AutoCancelled as exc:
                self.events.put(('cancelled', str(exc)))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=run, daemon=True).start()

    def prepare(self):
        try:
            options = AutoOptions(int(self.count.get()), self.style.get(), float(self.minimum.get()), float(self.maximum.get()))
            self.job = AutoJob(self.window.backend, self.window.media, options, self.pricing)
            self.work(lambda: self.job.prepare(self.cancel, lambda m: self.events.put(('progress', m))), 'prepared')
        except ValueError as exc:
            self.status.configure(text=str(exc), fg=t.RED)

    def local(self):
        if self.job and self.job.analysis:
            self.status.configure(text='Selecting distinct local-only candidates…', fg=t.CYAN)
            self.work(lambda: self.job.local(self.cancel), 'result')

    def ai(self):
        if self.job and self.job.request:
            key = self.key.get()
            saved = any((self.job.folder/name).exists() for name in ('ai-response.json','ai-result.json'))
            self.status.configure(text='Rechecking the saved AI response locally. No new paid request…' if saved else
                                  'AI is reviewing sampled frames. One paid request; no automatic retry…', fg=t.CYAN)
            self.work(lambda: self.job.ai(self.cancel, key), 'result')

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
                self.analyse_button.configure(state='normal')
                self.settings_button.configure(state='normal')
                for widget in self.inputs:
                    widget.configure(state='readonly' if isinstance(widget, ttk.Combobox) else 'normal')
                self.close_button.configure(text='CLOSE')
                ready = bool(self.job and self.job.analysis)
                self.local_button.configure(state='normal' if ready else 'disabled')
                quote = self.job.quote if ready else None
                allowed = bool(quote and quote['reserved_upper_gbp'] <= self.pricing.budget_gbp)
                saved = bool(ready and self.job.request and any((self.job.folder/name).exists()
                             for name in ('ai-response.json','ai-result.json')))
                self.ai_button.configure(state='normal' if allowed or saved else 'disabled',
                                         text='REUSE SAVED AI' if saved else 'CREATE WITH AI')
                self.folder_button.configure(state='normal' if ready else 'disabled')
                if kind == 'prepared':
                    cost = (f'AI estimate £{quote["estimated_gbp"]:.3f} total; reserve up to £{quote["reserved_upper_gbp"]:.3f}. '
                            f'Hard job cap £{self.pricing.budget_gbp:.2f}. '
                            + ('AI request blocked by budget. ' if not allowed else '') if quote else self.job.ai_error)
                    self.status.configure(text=cost+'\n'+self.job.transcript_note, fg=t.MUTED)
                elif kind == 'result':
                    self.show_results(*value)
                else:
                    self.status.configure(text=value, fg=t.RED if kind == 'error' else t.MUTED)
        except Empty:
            pass
        if self.closing and not self.busy:
            self.finish_close()
        elif not self.closed:
            self._poll = self.after(80, self.poll)

    def show_results(self, payload, path):
        self.payload = payload
        for widget in self.results.winfo_children():
            widget.destroy()
        usage = payload['usage']
        measured = usage.get('measured_cost_gbp')
        cost = f'£{measured:.4f} estimated from recorded usage' if measured is not None else f'up to £{usage["reserved_gbp"]:.4f} reserved; usage uncertain'
        self.status.configure(text=f'{payload["mode"]} · {len(payload["plan"]["shorts"])} candidates · {cost}\n'
                              + ('Reused AI result; no new charge. ' if payload['cached_ai_result'] else '')
                              + (f'{len(usage["timestamp_corrections"])} tiny timestamp corrections recorded. '
                                 if usage.get('timestamp_corrections') else '')
                              + self.job.transcript_note, fg=t.GREEN)
        for index, short in enumerate(payload['plan']['shorts']):
            row = tk.Frame(self.results, bg=t.PANEL)
            row.pack(fill='x', pady=4)
            duration = sum(s['end']-s['start'] for s in short['shots'])
            t.label(row, f'{index+1}. {short["title"]} · {duration:.1f}s\nSource {source_ranges(short["shots"])}', 10, bold=True,
                    wraplength=455, justify='left').pack(side='left', padx=10, pady=12)
            t.button(row, 'PREVIEW / EDIT', lambda s=short, p=payload: self.open_candidate(s, p)).pack(side='right', padx=10)

    def open_candidate(self, short, payload=None):
        from .editor_window import EditorWindow
        payload = payload or self.payload
        candidate = EditorWindow(self.window, self.window.path, self.window.backend,
                                 self.window.auto_children.discard,
                                 auto_candidate=(short, payload['transcript'], payload['mode'],
                                                 payload.get('options', {}).get('style', 'News/Preview')))
        self.window.auto_children.add(candidate)
        candidate.lift()

    def open_folder(self):
        if self.job and self.job.folder:
            os.startfile(str(self.job.folder))

    def close(self):
        self.closing = True
        self.cancel.set()
        self.key.set('')
        if self.busy:
            self.status.configure(text='Cancelling. A request already sent may still be charged; its reservation is retained.', fg=t.MUTED)
            self.close_button.configure(state='disabled')
        else:
            self.finish_close()

    def finish_close(self):
        if not self.closed:
            self.closed = True
            if self._poll:
                self.after_cancel(self._poll)
            self.destroy()
