"""Compact, explicitly manual API balance counter; no keys or billing requests."""
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import simpledialog
import webbrowser

from ui import theme as t
from .api_credits import CreditCounter


class CreditCounterPanel(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=t.PANEL)
        self.counter = CreditCounter()
        self.events = Queue()
        self.pending = False
        self.refresh_again = False
        self.label = t.label(self, 'API credits · checking local records…', 9, t.MUTED, anchor='w')
        self.label.pack(side='left', fill='x', expand=True, padx=10)
        for title, command in [('SET BALANCE', self.set_balance), ('REFRESH', self.refresh),
                                ('OPEN BILLING', self.open_billing)]:
            button = t.button(self, title, command)
            button.configure(padx=7, pady=5)
            button.pack(side='left', padx=2)
        self.refresh()
        self.timer = self.after(100, self.poll)

    def open_billing(self):
        webbrowser.open('https://platform.openai.com/settings/organization/billing/overview')

    def set_balance(self):
        value = simpledialog.askfloat('Reconcile API credits (USD)',
            'Enter the current USD balance shown in OpenAI billing.\n'
            'This marks existing local requests as reconciled.\n'
            'Other apps, credit expiry and delayed charges are not tracked.',
            parent=self, minvalue=0, maxvalue=1_000_000)
        if value is not None:
            try:
                self.counter.reconcile(value)
                self.refresh()
            except (OSError, ValueError) as exc:
                self.label.configure(text=str(exc), fg=t.RED)

    def refresh(self):
        if self.pending:
            self.refresh_again = True
            return
        self.pending = True
        def worker():
            try:
                self.events.put(self.counter.summary())
            except (OSError, ValueError, TypeError) as exc:
                self.events.put(str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            result = self.events.get_nowait()
            self.pending = False
            if isinstance(result, str):
                self.label.configure(text='Credit records unavailable: '+result, fg=t.RED)
            else:
                balance = result['remaining_estimate_usd']
                unknown = result['unpriced_requests']
                if unknown:
                    text = f'API credits · billing check needed · {unknown} unpriced request(s)'
                elif balance is None:
                    text = 'API credits · set your billing balance to start tracking'
                else:
                    text = f'API credits · ${balance:.4f} USD remaining estimate (local)'
                text += f'\nRecorded GPT estimate: ${result["estimated_spend_usd"]:.4f} · {result["requests_since_check"]} requests since check'
                self.label.configure(text=text, fg=t.MUTED)
            if self.refresh_again:
                self.refresh_again = False
                self.refresh()
        except Empty:
            pass
        self.timer = self.after(100, self.poll)

    def close(self):
        self.after_cancel(self.timer)
