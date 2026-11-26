"""Small timed-caption editor shared by automatic and manual edits."""
from dataclasses import replace, asdict
import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, colorchooser, simpledialog
from ui import theme as t
from .models import format_time, parse_time
from .text_overlay import Caption
from .typography import CaptionStyle, THEMES, theme_style
from .caption_fonts import installed_fonts, resolve_family
from .edit_history import EditHistory, EditSnapshot


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



def load_style_library():
    result = {'presets': {}, 'recent': []}
    try:
        data = json.loads(_preferences_path().with_name('caption_presets.json').read_text(encoding='utf-8'))
        for name, values in data.get('presets', {}).items():
            if not isinstance(name, str) or name in THEMES: continue
            try:
                CaptionStyle(**values).validate()
                result['presets'][name] = values
            except (TypeError, ValueError): pass
        import re
        result['recent'] = [c for c in data.get('recent', []) if isinstance(c,str) and re.fullmatch('#[0-9A-Fa-f]{6}',c)][:12]
    except (OSError, ValueError, TypeError, AttributeError): pass
    return result


def save_style_library(data):
    path = _preferences_path().with_name('caption_presets.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(temp, path)


class CaptionDialog(tk.Toplevel):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        pulse = bool(getattr(window, 'pulse_candidate', None))
        self.title('Timed captions · output timestamps' if pulse else 'Timed captions · source timestamps')
        self.configure(bg=t.BG)
        self.geometry(f'840x{min(820, self.winfo_screenheight()-100)}')
        self.transient(window)
        self._loading = True
        self._live_id = None
        self._dragging = False
        self.fonts = tuple(sorted(installed_fonts(), key=str.casefold))
        self.library = load_style_library()
        self._bindtag = f'CaptionDrag{id(self)}'
        window.video.bindtags((self._bindtag,) + window.video.bindtags())
        window.video.bind_class(self._bindtag, '<Button-1>', self.begin_video_drag)
        window.video.bind_class(self._bindtag, '<B1-Motion>', self.drag_video)
        window.video.bind_class(self._bindtag, '<ButtonRelease-1>', self.end_video_drag)
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.captions = list(window.edits.text.captions)
        self.rows = tk.Listbox(self, height=4, bg=t.CONTROL, fg=t.TEXT, exportselection=False)
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
        picker = ttk.Combobox(styles, textvariable=self.theme, values=(*THEMES, *self.library['presets']), state='readonly', width=20)
        picker.pack(side='left', padx=8)
        self.picker = picker
        picker.bind('<<ComboboxSelected>>', self.choose_preset)
        t.button(styles, 'SAVE PRESET', self.save_preset).pack(side='left')
        self.style_vars = {}
        scroller = tk.Frame(self, bg=t.BG)
        scroller.pack(fill='both', expand=True, padx=16)
        scroll = tk.Canvas(scroller, bg=t.BG, height=240, highlightthickness=0)
        bar = ttk.Scrollbar(scroller, orient='vertical', command=scroll.yview)
        bar.pack(side='right', fill='y')
        scroll.pack(side='left', fill='both', expand=True)
        scroll.configure(yscrollcommand=bar.set)
        settings = tk.Frame(scroll, bg=t.BG)
        inner = scroll.create_window(0, 0, window=settings, anchor='nw')
        settings.bind('<Configure>', lambda _: scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>', lambda e: scroll.itemconfigure(inner, width=e.width))
        for col in range(4): settings.columnconfigure(col, weight=1)
        for i, (key, value) in enumerate(asdict(initial).items()):
            if key == 'theme':
                continue
            group = tk.Frame(settings, bg=t.BG)
            group.grid(row=(i-1)//4, column=(i-1)%4, padx=(0,8), pady=3, sticky='ew')
            t.label(group, key.replace('_',' ').title(), 9).pack(anchor='w')
            if isinstance(value, bool):
                var = tk.BooleanVar(value=value)
                tk.Checkbutton(group, text='ON', variable=var, bg=t.BG, fg=t.TEXT,
                               selectcolor=t.CONTROL, activebackground=t.BG).pack(anchor='w')
            else:
                var = tk.StringVar(value=str(value))
                if key in ('alignment','animation','font_family'):
                    options = (('left','centre','right') if key == 'alignment' else
                               ('none','fade','pop','shake') if key == 'animation' else self.fonts)
                    combo = ttk.Combobox(group, textvariable=var, values=options,
                                 state='normal' if key == 'font_family' else 'readonly', width=12)
                    combo.pack(fill='x')
                    if key == 'font_family':
                        combo.bind('<KeyRelease>', lambda _, c=combo: c.configure(
                            values=[name for name in self.fonts if c.get().casefold() in name.casefold()]))
                elif key.endswith('colour'):
                    colour_row = tk.Frame(group, bg=t.BG)
                    colour_row.pack(fill='x')
                    tk.Entry(colour_row, textvariable=var, width=9).pack(side='left', fill='x', expand=True)
                    tk.Button(colour_row, text='…', command=lambda v=var: self.pick_colour(v),
                              width=2, bg=t.CONTROL, fg=t.TEXT, relief='flat').pack(side='right')
                else:
                    tk.Entry(group, textvariable=var, width=13).pack(fill='x')
            self.style_vars[key] = var
        for var in self.style_vars.values():
            var.trace_add('write', self.style_changed)
        self.style_enabled.trace_add('write', self.style_changed)
        self.position.trace_add('write', self.style_changed)
        self.input.bind('<KeyRelease>', lambda _: self.refresh_preview())
        self.preview = tk.Canvas(self, height=124, bg='#101827', highlightthickness=1,
                                 highlightbackground=t.CYAN, cursor='fleur')
        self.preview.pack(fill='x', padx=16, pady=(8, 6))
        self.preview.bind('<Configure>', lambda _: self.refresh_preview())
        self.preview.bind('<B1-Motion>', self.drag_preview)
        t.label(self, 'Select a caption, then drag on the video · Style changes appear live',
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
        self._loading = False
        self.refresh_preview()

    def read_style(self):
        if not self.style_enabled.get():
            return None
        values = {}
        for key, var in self.style_vars.items():
            value = var.get()
            if key in ('font_size', 'outline', 'shadow', 'shadow_x', 'shadow_y'):
                value = int(value)
            elif key in ('band_width', 'band_y', 'background_opacity', 'x_offset', 'y_offset', 'shadow_opacity'):
                value = float(value)
            values[key] = value
        style = CaptionStyle(theme=self.theme.get(), **values)
        style.validate()
        return style

    def pick_colour(self, variable):
        chooser = tk.Toplevel(self)
        chooser.title('Caption colour')
        chooser.configure(bg=t.BG)
        def choose(value):
            variable.set(value.upper())
            self.library['recent'] = ([value.upper()] + [c for c in self.library['recent'] if c != value.upper()])[:12]
            save_style_library(self.library)
            chooser.destroy()
        colours = ('#FFFFFF','#000000','#27DEF5','#FFD83D','#FF4466','#9955FF', *self.library['recent'])
        for i, colour in enumerate(dict.fromkeys(colours)):
            tk.Button(chooser, bg=colour, width=4, command=lambda c=colour: choose(c)).grid(row=i//6, column=i%6, padx=4, pady=4)
        def full_picker():
            try: initial = variable.get() if len(variable.get()) == 7 else '#FFFFFF'
            except tk.TclError: initial = '#FFFFFF'
            result = colorchooser.askcolor(color=initial, parent=chooser)
            if result and result[1]: choose(result[1])
        tk.Button(chooser, text='Full colour picker…', command=full_picker).grid(row=4,column=0,columnspan=6,sticky='ew')

    def choose_preset(self, _=None):
        name = self.theme.get()
        self.set_style(CaptionStyle(**self.library['presets'][name]) if name in self.library['presets'] else theme_style(name))

    def save_preset(self):
        try:
            style = self.read_style()
            if style is None: raise ValueError('Enable styled captions first.')
            name = simpledialog.askstring('Save caption preset', 'Preset name:', parent=self)
            if not name or not name.strip(): return
            name = name.strip()[:80]
            if name in THEMES: raise ValueError('Choose a new name to preserve the built-in preset.')
            self.library['presets'][name] = asdict(style)
            save_style_library(self.library)
            self.picker.configure(values=(*THEMES, *self.library['presets']))
            self.note.configure(text=f'Saved preset: {name}', fg=t.GREEN)
        except (ValueError, OSError) as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def style_changed(self, *_):
        self.refresh_preview()
        if self._loading: return
        if self._live_id: self.after_cancel(self._live_id)
        self._live_id = self.after(220, self.apply_selected_style)

    def apply_selected_style(self):
        self._live_id = None
        if not self.rows.curselection() or self.window.exporter.busy: return
        try:
            index = self.rows.curselection()[0]
            proposed = list(self.captions)
            proposed[index] = replace(proposed[index], style=self.read_style(), position=self.position.get())
            if proposed != self.captions: self.commit(proposed)
            self.note.configure(text='Style updated on the video. Text and timings are unchanged.', fg=t.GREEN)
        except (ValueError, tk.TclError) as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def begin_video_drag(self, event):
        w = self.window
        bounds = w.video.bounds()
        if not bounds or not self.rows.curselection() or w.playing or w.exporter.busy or w.video.source_view: return
        left, top, width, height = bounds
        if not (left <= event.x <= left+width and top <= event.y <= top+height): return
        self._dragging = True
        self.drag_video(event)
        return 'break'

    def drag_video(self, event):
        if not self._dragging: return
        bounds = self.window.video.bounds()
        if bounds:
            left, top, width, height = bounds
            self.place_at((event.x-left)/width, (event.y-top)/height)
        return 'break'

    def end_video_drag(self, event):
        if self._dragging:
            self.drag_video(event)
            self._dragging = False
            return 'break'

    def place_at(self, x, y):
        try:
            style = self.read_style()
            if style is None: return
            if self.window.edits.comedy_bands:
                self.position.set('Top' if y < .5 else 'Bottom')
                bands = self.window.edits.bands(self.window.media)
                band = bands[self.position.get().lower()]
                _, height = self.window.edits.encoded_size(self.window.media)
                self.style_vars['band_y'].set(f'{max(0,min(1,(y*height-band.y)/band.height)):.3f}')
            else:
                # Centre anchors give direct manipulation over the complete safe canvas.
                self.position.set('Centre')
                self.style_vars['alignment'].set('centre')
                self.style_vars['x_offset'].set(f'{max(-.4,min(.4,x-.5)):.3f}')
                self.style_vars['y_offset'].set(f'{max(-.4,min(.4,y-.5)):.3f}')
        except (ValueError, tk.TclError): pass

    def destroy(self):
        if self._live_id:
            self.after_cancel(self._live_id)
            self.apply_selected_style()
        video = self.window.video
        if video.winfo_exists():
            video.bindtags(tuple(tag for tag in video.bindtags() if tag != self._bindtag))
            for event in ('<Button-1>', '<B1-Motion>', '<ButtonRelease-1>'):
                video.unbind_class(self._bindtag, event)
        super().destroy()

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
        face = (resolve_family(style.font_family), size, ' '.join(filter(None, ('bold' if style.bold else 'normal', 'italic' if style.italic else '', 'underline' if style.underline else ''))))
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
                               fill=style.shadow_colour, **common)
        if style.outline:
            for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
                canvas.create_text(x+dx, y+dy, fill=style.outline_colour, **common)
        canvas.create_text(x, y, fill=style.colour, **common)

    def drag_preview(self, event):
        self.place_at(event.x/max(1,self.preview.winfo_width()), event.y/124)

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
        loading, self._loading = self._loading, True
        self.style_enabled.set(style is not None)
        style = style or CaptionStyle()
        self.theme.set(style.theme)
        for key, var in self.style_vars.items():
            var.set(getattr(style, key))
        self._loading = loading
        self.style_changed()

    def refresh(self):
        selected = self.rows.curselection()
        self.rows.delete(0, 'end')
        for cue in self.captions:
            self.rows.insert('end', f'{format_time(cue.start)} – {format_time(cue.end)}  {cue.text.replace(chr(10), " / ")}')

        if selected and selected[0] < len(self.captions): self.rows.selection_set(selected[0])

    def select(self, _=None):
        if self.rows.curselection():
            self._loading = True
            cue = self.captions[self.rows.curselection()[0]]
            self.start.set(format_time(cue.start))
            self.end.set(format_time(cue.end))
            self.position.set(cue.position)
            self.set_style(cue.style)
            self.input.delete('1.0', 'end')
            self.input.insert('1.0', cue.text)
            self._loading = False
            self.window.seek(min(cue.end-.01, cue.start+.2))
            self.refresh_preview()

    def commit(self, proposed):
        w = self.window
        edits = replace(w.edits, text=replace(w.edits.text, captions=tuple(proposed), safe_area=True))
        edits.validate(w.media)
        w.stop_play()
        before = EditSnapshot(w.trim, w.cuts, w.edits)
        if w.timeline_history is None or w.timeline_history.current != before:
            w.timeline_history = EditHistory(before)
        w.edits = edits
        w.timeline_history.record(EditSnapshot(w.trim, w.cuts, edits))
        w.update_timeline()
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
