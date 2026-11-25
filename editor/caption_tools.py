"""Small timed-caption editor shared by automatic and manual edits."""
from dataclasses import replace, asdict
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, colorchooser
from ui import theme as t
from .models import format_time, parse_time
from .text_overlay import Caption
from .typography import CaptionStyle, THEMES, FONT_FAMILIES, theme_style


def _preferences_path():
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Pulse Capture' / 'caption_style.json'


def load_caption_preference():
    """Style preferences only; never touch capture projects or stored media."""
    try:
        data = json.loads(_preferences_path().read_text(encoding='utf-8'))
        style = CaptionStyle(**data)
        style.validate()
        return style
    except (OSError, TypeError, ValueError, KeyError):
        return CaptionStyle()


def save_caption_preference(style):
    """Best-effort atomic save; a locked settings directory must not block edits."""
    if style is None:
        return
    style.validate()
    try:
        path = _preferences_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(asdict(style), indent=2), encoding='utf-8')
        os.replace(temp, path)
    except OSError:
        pass


class CaptionDialog(tk.Toplevel):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        pulse = bool(getattr(window, 'pulse_candidate', None))
        self.title('Timed captions · output timestamps' if pulse else 'Timed captions · source timestamps')
        self.configure(bg=t.BG)
        self.geometry('840x820')
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
        initial = load_caption_preference()
        self.theme = tk.StringVar(value=initial.theme)
        picker = ttk.Combobox(styles, textvariable=self.theme, values=THEMES, state='readonly', width=20)
        picker.pack(side='left', padx=8)
        picker.bind('<<ComboboxSelected>>', lambda _: self.set_style(theme_style(self.theme.get())))
        self.style_vars = {}
        settings = tk.Frame(self, bg=t.BG)
        settings.pack(fill='x', padx=16)
        for i, (key, value) in enumerate(asdict(initial).items()):
            if key == 'theme':
                continue
            group = tk.Frame(settings, bg=t.BG)
            group.grid(row=(i-1)//5, column=(i-1)%5, padx=(0,8), pady=3, sticky='ew')
            t.label(group, key.replace('_',' ').title(), 9).pack(anchor='w')
            if isinstance(value, bool):
                var = tk.BooleanVar(value=value)
                tk.Checkbutton(group, text='ON', variable=var, bg=t.BG, fg=t.TEXT,
                               selectcolor=t.CONTROL, activebackground=t.BG).pack(anchor='w')
            else:
                var = tk.StringVar(value=str(value))
                if key in ('alignment','animation','font_family'):
                    options = (('left','centre','right') if key == 'alignment' else
                               ('none','fade','pop','shake') if key == 'animation' else FONT_FAMILIES)
                    ttk.Combobox(group, textvariable=var, values=options,
                                 state='readonly', width=12).pack(fill='x')
                elif key in ('colour','highlight_colour','background_colour'):
                    colour_row = tk.Frame(group, bg=t.BG)
                    colour_row.pack(fill='x')
                    tk.Entry(colour_row, textvariable=var, width=9).pack(side='left', fill='x', expand=True)
                    tk.Button(colour_row, text='…', command=lambda v=var: self.pick_colour(v),
                              width=2, bg=t.CONTROL, fg=t.TEXT, relief='flat').pack(side='right')
                else:
                    tk.Entry(group, textvariable=var, width=13).pack(fill='x')
            self.style_vars[key] = var
        for var in self.style_vars.values():
            var.trace_add('write', lambda *_: self.refresh_preview())
        self.style_enabled.trace_add('write', lambda *_: self.refresh_preview())
        self.position.trace_add('write', lambda *_: self.refresh_preview())
        self.input.bind('<KeyRelease>', lambda _: self.refresh_preview())
        self.preview = tk.Canvas(self, height=124, bg='#101827', highlightthickness=1,
                                 highlightbackground=t.CYAN, cursor='fleur')
        self.preview.pack(fill='x', padx=16, pady=(8, 6))
        self.preview.bind('<Configure>', lambda _: self.refresh_preview())
        self.preview.bind('<B1-Motion>', self.drag_preview)
        t.label(self, 'DRAG PREVIEW TO REPOSITION · Update to see exact video rendering',
                9, t.MUTED).pack(anchor='w', padx=16, pady=(0,6))
        actions = tk.Frame(self, bg=t.BG)
        actions.pack(fill='x', padx=16)
        for label, command in (('ADD', lambda: self.save(False)), ('UPDATE', lambda: self.save(True)),
                               ('APPLY STYLE TO ALL', self.apply_style_all),
                               ('REMOVE', self.remove), ('DONE', self.destroy)):
            t.button(actions, label, command).pack(side='left', padx=(0, 8))
        self.note = t.label(self, 'Caption times refer to the assembled Pulse output.' if pulse else
                            'Caption times stay anchored to the original video.', 10, t.MUTED, wraplength=580)
        self.note.pack(fill='x', padx=16, pady=12)
        if window.edits.comedy_bands:
            self.set_style(CaptionStyle(font_size=104))
            self.note.configure(text='Top / Bottom use safe comedy bands. Band width: .3–1; Band y: 0–1 within the band.')
        self.refresh()
        self.refresh_preview()

    def read_style(self):
        if not self.style_enabled.get():
            return None
        values = {}
        for key, var in self.style_vars.items():
            value = var.get()
            if key in ('font_size', 'outline', 'shadow'):
                value = int(value)
            elif key in ('band_width', 'band_y', 'background_opacity', 'x_offset', 'y_offset'):
                value = float(value)
            values[key] = value
        style = CaptionStyle(theme=self.theme.get(), **values)
        style.validate()
        return style

    def pick_colour(self, variable):
        result = colorchooser.askcolor(color=variable.get(), parent=self)
        if result and result[1]:
            variable.set(result[1].upper())

    def refresh_preview(self):
        if not hasattr(self, 'preview') or not self.preview.winfo_exists():
            return
        canvas = self.preview
        canvas.delete('all')
        width, height = max(200, canvas.winfo_width()), 124
        canvas.create_rectangle(0, 0, width, height, fill='#101827', outline='')
        canvas.create_line(0, height*.5, width, height*.5, fill='#243044')
        try:
            style = self.read_style()
        except (ValueError, tk.TclError):
            canvas.create_text(width/2, height/2, text='Check caption style values',
                               fill='#FFA1A1', font=('Segoe UI', 12))
            return
        if style is None:
            style = CaptionStyle(font_family='Arial', font_size=76, outline=0, shadow=0,
                                 background_enabled=True, background_opacity=.65)
        sample = self.input.get('1.0','end-1c').strip() or 'YOUR CAPTION APPEARS HERE'
        sample = sample[:110]
        x_base = {'left':.15, 'centre':.5, 'right':.85}[style.alignment]
        y_base = {'Top':.22, 'Centre':.5, 'Bottom':.78}[self.position.get()]
        x = width*max(.07, min(.93, x_base+style.x_offset))
        y = height*max(.07, min(.93, y_base+style.y_offset))
        size = max(10, min(27, round(style.font_size*.24)))
        face = (style.font_family, size, 'bold' if style.bold else 'normal')
        justify = {'left':'left','centre':'center','right':'right'}[style.alignment]
        width_limit = round(width*.74)
        common = dict(text=sample, font=face, justify=justify, width=width_limit)
        marker = canvas.create_text(x, y, fill=style.colour, **common)
        bbox = canvas.bbox(marker)
        canvas.delete(marker)
        if style.background_enabled and bbox:
            alpha = style.background_opacity
            base = (16, 24, 39)
            rgb = tuple(round(int(style.background_colour[k:k+2],16)*alpha+base[i]*(1-alpha))
                        for i,k in enumerate((1,3,5)))
            fill = '#%02X%02X%02X' % rgb
            canvas.create_rectangle(bbox[0]-8, bbox[1]-4, bbox[2]+8, bbox[3]+4,
                                    fill=fill, outline='')
        if style.shadow:
            canvas.create_text(x+min(3, style.shadow), y+min(3,style.shadow),
                               fill='#050505', **common)
        if style.outline and not style.background_enabled:
            for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
                canvas.create_text(x+dx, y+dy, fill='#050505', **common)
        canvas.create_text(x, y, fill=style.colour, **common)

    def drag_preview(self, event):
        if self.window.edits.comedy_bands:
            return
        try:
            width, height = max(1, self.preview.winfo_width()), 124
            style = self.read_style()
            if style is None:
                return
            base_x = {'left':.15,'centre':.5,'right':.85}[style.alignment]
            base_y = {'Top':.22,'Centre':.5,'Bottom':.78}[self.position.get()]
            dx = max(-.4, min(.4, event.x/width-base_x))
            dy = max(-.4, min(.4, event.y/height-base_y))
            self.style_vars['x_offset'].set(f'{dx:.3f}')
            self.style_vars['y_offset'].set(f'{dy:.3f}')
        except (ValueError, tk.TclError):
            pass

    def apply_style_all(self):
        try:
            if not self.captions:
                raise ValueError('Add a caption first.')
            style = self.read_style()
            self.commit([replace(cue, style=style) for cue in self.captions])
            save_caption_preference(style)
            self.note.configure(text='Style applied to all captions.', fg=t.GREEN)
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)

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
            style = self.read_style()
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
            save_caption_preference(style)
            self.note.configure(text='Caption saved.', fg=t.GREEN)
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def remove(self):
        if self.rows.curselection():
            proposed = list(self.captions)
            del proposed[self.rows.curselection()[0]]
            self.commit(proposed)
