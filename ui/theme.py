"""Reusable Pulse design tokens and compact desktop components."""
import tkinter as tk
from tkinter import ttk

BG = '#0b1017'
PANEL = '#121b26'
CONTROL = '#1a2837'
LINE = '#28394b'
TEXT = '#ecf3fc'
MUTED = '#92a6bc'
CYAN = '#55dded'
RED = '#ff596c'
GREEN = '#68e4b3'
FONT = 'Segoe UI'
MONO = 'Consolas'


def install(root):
    root.configure(bg=BG)
    root.option_add('*Font', (FONT, -13))
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('Vertical.TScrollbar', background=CONTROL, troughcolor=BG,
                    bordercolor=BG, arrowcolor=MUTED, lightcolor=BG, darkcolor=BG)
    style.configure('TCombobox', fieldbackground=CONTROL, background=CONTROL,
                    foreground=TEXT, arrowcolor=CYAN, bordercolor=LINE, padding=5)
    style.map('TCombobox', fieldbackground=[('readonly', CONTROL), ('disabled', PANEL)],
              foreground=[('disabled', MUTED), ('readonly', TEXT)],
              selectbackground=[('readonly', CONTROL)], selectforeground=[('readonly', TEXT)])
    root.option_add('*TCombobox*Listbox.background', CONTROL)
    root.option_add('*TCombobox*Listbox.foreground', TEXT)
    root.option_add('*TCombobox*Listbox.selectBackground', LINE)


def label(parent, text='', size=10, color=TEXT, bold=False, **kw):
    return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                    font=(FONT, -round(size * 1.3), 'bold' if bold else 'normal'), **kw)


def button(parent, text, command, accent=False, **kw):
    return tk.Button(parent, text=text, command=command, bg=CYAN if accent else CONTROL,
                     fg=BG if accent else TEXT, activebackground=LINE,
                     activeforeground=TEXT, disabledforeground=MUTED, relief='flat',
                     bd=0, padx=14, pady=7, cursor='hand2', **kw)


class Card(tk.Frame):
    def __init__(self, parent, number, title, **kw):
        super().__init__(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1, **kw)
        head = tk.Frame(self, bg=PANEL)
        head.pack(fill='x', padx=18, pady=(10, 7))
        label(head, number, 9, CYAN, True).pack(side='left', padx=(0, 9))
        label(head, title, 9, MUTED, True).pack(side='left')
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill='x', padx=18, pady=(0, 10))


class Segments(tk.Frame):
    def __init__(self, parent, variable, choices, command=None):
        super().__init__(parent, bg=PANEL)
        self.variable, self.buttons = variable, []
        for i, (value, title) in enumerate(choices):
            b = button(self, title, lambda v=value: self.choose(v, command))
            b.grid(row=0, column=i, sticky='ew', padx=(0 if i == 0 else 5, 0))
            self.columnconfigure(i, weight=1)
            self.buttons.append((value, b))
        variable.trace_add('write', lambda *_: self.paint())
        self.paint()

    def choose(self, value, command):
        self.variable.set(value)
        if command:
            command()

    def paint(self):
        for value, b in self.buttons:
            selected = str(value) == str(self.variable.get())
            b.configure(bg=CYAN if selected else CONTROL, fg=BG if selected else TEXT)

    def enable(self, enabled):
        for _, b in self.buttons:
            b.configure(state='normal' if enabled else 'disabled')
