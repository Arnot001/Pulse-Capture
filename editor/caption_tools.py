"""Small timed-caption editor shared by automatic and manual edits."""
from dataclasses import replace, asdict
import tkinter as tk
from tkinter import ttk
from ui import theme as t
from .models import format_time, parse_time
from .text_overlay import Caption
from .typography import CaptionStyle, THEMES, theme_style


class CaptionDialog(tk.Toplevel):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        pulse = bool(getattr(window, 'pulse_candidate', None))
        self.title('Timed captions · output timestamps' if pulse else 'Timed captions · source timestamps')
        self.configure(bg=t.BG)
        self.geometry('680x620')
        self.transient(window)
        self.grab_set()
        self.captions = list(window.edits.text.captions)
        self.rows = tk.Listbox(self, bg=t.CONTROL, fg=t.TEXT, exportselection=False)
        self.rows.pack(fill='both', expand=True, padx=16, pady=12)
        self.rows.bind('<<ListboxSelect>>', self.select)
        fields = tk.Frame(self, bg=t.BG)
        fields.pack(fill='x', padx=16)
        self.start = tk.StringVar(value=format_time(window.position))
        self.end = tk.StringVar(value=format_time(min(window.media.duration, window.position+3)))
        self.position = tk.StringVar(value='Bottom')
        for label, var in (('Start', self.start), ('End', self.end)):
            t.label(fields, label, 10).pack(side='left')
            tk.Entry(fields, textvariable=var, width=12).pack(side='left', padx=6)
        ttk.Combobox(fields, textvariable=self.position, values=('Top','Bottom') if window.edits.comedy_bands else ('Top', 'Centre', 'Bottom'),
                     state='readonly', width=9).pack(side='left')
        self.input = tk.Text(self, height=3, bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN)
        self.input.pack(fill='x', padx=16, pady=10)
        self.style_enabled = tk.BooleanVar(value=True)
        styles = tk.Frame(self, bg=t.BG)
        styles.pack(fill='x', padx=16, pady=4)
        tk.Checkbutton(styles, text='Styled captions', variable=self.style_enabled, bg=t.BG, fg=t.TEXT,
                       selectcolor=t.CONTROL).pack(side='left')
        self.theme = tk.StringVar(value='Comedy Bold')
        picker = ttk.Combobox(styles, textvariable=self.theme, values=THEMES, state='readonly', width=20)
        picker.pack(side='left', padx=8)
        picker.bind('<<ComboboxSelected>>', lambda _: self.set_style(theme_style(self.theme.get())))
        self.style_vars = {}
        settings = tk.Frame(self, bg=t.BG)
        settings.pack(fill='x', padx=16)
        for i, (key, value) in enumerate(asdict(CaptionStyle()).items()):
            if key == 'theme':
                continue
            group = tk.Frame(settings, bg=t.BG)
            group.grid(row=(i-1)//4, column=(i-1)%4, padx=(0,8), pady=3, sticky='ew')
            t.label(group, key.replace('_',' ').title(), 9).pack(anchor='w')
            var = tk.StringVar(value=str(value))
            self.style_vars[key] = var
            if key in ('alignment','animation'):
                ttk.Combobox(group, textvariable=var, values=('left','centre','right') if key=='alignment' else
                             ('none','fade','pop','shake'), state='readonly', width=12).pack(fill='x')
            else:
                tk.Entry(group, textvariable=var, width=14).pack(fill='x')
        actions = tk.Frame(self, bg=t.BG)
        actions.pack(fill='x', padx=16)
        for label, command in (('ADD', lambda: self.save(False)), ('UPDATE', lambda: self.save(True)),
                               ('REMOVE', self.remove), ('DONE', self.destroy)):
            t.button(actions, label, command).pack(side='left', padx=(0, 8))
        self.note = t.label(self, 'Caption times refer to the assembled Pulse output.' if pulse else
                            'Caption times stay anchored to the original video.', 10, t.MUTED, wraplength=580)
        self.note.pack(fill='x', padx=16, pady=12)
        if window.edits.comedy_bands:
            self.set_style(CaptionStyle(font_size=104))
            self.note.configure(text='Top / Bottom use safe comedy bands. Band width: .3–1; Band y: 0–1 within the band.')
        self.refresh()

    def set_style(self, style):
        self.style_enabled.set(style is not None)
        style = style or CaptionStyle()
        self.theme.set(style.theme)
        for key, var in self.style_vars.items():
            var.set(str(getattr(style, key)))

    def refresh(self):
        self.rows.delete(0, 'end')
        for cue in self.captions:
            self.rows.insert('end', f'{format_time(cue.start)} – {format_time(cue.end)}  {cue.text.replace(chr(10), " / ")}')

    def select(self, _=None):
        if self.rows.curselection():
            cue = self.captions[self.rows.curselection()[0]]
            self.start.set(format_time(cue.start))
            self.end.set(format_time(cue.end))
            self.position.set(cue.position)
            self.set_style(cue.style)
            self.input.delete('1.0', 'end')
            self.input.insert('1.0', cue.text)
            self.window.seek(cue.start)

    def commit(self, proposed):
        w = self.window
        edits = replace(w.edits, text=replace(w.edits.text, captions=tuple(proposed), safe_area=True))
        edits.validate(w.media)
        w.stop_play()
        w.edits = edits
        self.captions = proposed
        self.refresh()
        w.request_frame()

    def save(self, update):
        try:
            values = {key: (int(var.get()) if key in ('font_size','outline','shadow') else
                            float(var.get()) if key in ('band_width','band_y') else var.get())
                      for key, var in self.style_vars.items()}
            style = CaptionStyle(theme=self.theme.get(), **values) if self.style_enabled.get() else None
            cue = Caption(parse_time(self.start.get()), parse_time(self.end.get()),
                          self.input.get('1.0', 'end-1c'), self.position.get(), style)
            proposed = list(self.captions)
            if update:
                if not self.rows.curselection():
                    raise ValueError('Select a caption to update.')
                proposed[self.rows.curselection()[0]] = cue
            else:
                proposed.append(cue)
            self.commit(proposed)
            self.note.configure(text='Caption saved.', fg=t.GREEN)
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def remove(self):
        if self.rows.curselection():
            proposed = list(self.captions)
            del proposed[self.rows.curselection()[0]]
            self.commit(proposed)
