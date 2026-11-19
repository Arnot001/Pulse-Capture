"""Record/import, catalogue, local conversion and output-track controls in one panel."""
from dataclasses import replace
from pathlib import Path
from queue import Queue, Empty
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from ui import theme as t
from .ai_voiceover import library_root
from .narration import Narration
from .voice_assets import VoiceSettings, import_audio, process_voice, waveform, wav_info
from .voice_catalogue import Catalogue, CATEGORIES
from .voice_conversion import convert_voice, available
from .voice_recording import MicrophoneRecorder, microphones


def button(parent, text, command, **kwargs):
    padding = kwargs.pop('padx', 14)
    widget = t.button(parent, text, command, **kwargs)
    widget.configure(padx=padding)
    return widget


class ChangeVoicePanel(tk.Frame):
    def __init__(self, parent, studio):
        super().__init__(parent, bg=t.BG)
        self.studio = studio
        self.original = self.converted = self.output = None
        self.busy = False
        self.cancel = threading.Event()
        self.events = Queue()
        self.recorder = MicrophoneRecorder()
        self.catalogue = Catalogue()
        self.devices = []
        self.visible = []
        self.wave_points = []
        self.device = tk.StringVar()
        self.query = tk.StringVar()
        self.category = tk.StringVar(value='All')
        self.sort = tk.StringVar(value='Name')
        self.favourites = tk.BooleanVar()
        self.values = {key: tk.DoubleVar(value=value) for key, value in
                       [('speed', 1), ('pitch', 0), ('volume', 1), ('mix', 1)]}
        self.flags = {key: tk.BooleanVar() for key in ('normalize', 'denoise', 'trim_edges')}
        self.start = tk.DoubleVar(value=0)
        self.duck = tk.DoubleVar(value=.35)
        self.track_volume = tk.DoubleVar(value=1)
        self._build()
        self.refresh_catalogue()
        self.at_playhead()
        current = getattr(getattr(studio.master, 'edits', None), 'narration', None)
        if current:
            self.start.set(current.start)
            self.duck.set(current.background_gain)
            self.track_volume.set(current.volume)
            self.show_audio('original', current.file)
        self.background(self.load_devices, 'Finding microphones…')
        self.timer = self.after(80, self.poll)

    def _build(self):
        record = tk.Frame(self, bg=t.PANEL)
        record.pack(fill='x', padx=12, pady=8)
        ttk.Combobox(record, textvariable=self.device, values=(), state='readonly', width=35).pack(side='left', padx=6)
        self.device_box = record.winfo_children()[-1]
        for title, callback in [('RECORD / RETAKE', self.record), ('PAUSE / RESUME', self.recorder.pause),
                                ('STOP', self.recorder.stop), ('IMPORT', self.import_recording)]:
            button(record, title, callback, padx=7) .pack(side='left', padx=2)
        self.meter = ttk.Progressbar(self, maximum=1)
        self.meter.pack(fill='x', padx=12)
        self.take_info = t.label(self, 'Original recordings are kept locally. Retake creates a new file.', 9, t.MUTED)
        self.take_info.pack(anchor='w', padx=12)
        self.wave = tk.Canvas(self, height=70, bg=t.PANEL, highlightthickness=0)
        self.wave.pack(fill='x', padx=12, pady=5)
        self.wave.bind('<Configure>', lambda _: self.draw_wave())
        search = tk.Frame(self, bg=t.BG)
        search.pack(fill='x', padx=12)
        t.label(search, 'Search voices', 9).pack(side='left', padx=(0, 6))
        tk.Entry(search, textvariable=self.query, bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN).pack(side='left', fill='x', expand=True)
        ttk.Combobox(search, textvariable=self.category, values=CATEGORIES, state='readonly', width=13).pack(side='left', padx=5)
        ttk.Combobox(search, textvariable=self.sort, values=('Name', 'Recently used'), state='readonly', width=14).pack(side='left')
        tk.Checkbutton(search, text='Favourites', variable=self.favourites, bg=t.BG, fg=t.TEXT,
                       selectcolor=t.CONTROL, command=self.refresh_catalogue).pack(side='left')
        self.filters = {}
        self.filter_boxes = {}
        filters = tk.Frame(self, bg=t.BG)
        filters.pack(fill='x', padx=12, pady=4)
        for name in ('accent', 'language', 'age', 'tone', 'style'):
            t.label(filters, name.title(), 9).pack(side='left')
            variable = tk.StringVar(value='All')
            values = ('All',) + tuple(sorted({getattr(v, name) for v in self.catalogue.voices()}))
            box = ttk.Combobox(filters, textvariable=variable, values=values, state='readonly', width=12)
            box.pack(side='left', padx=3)
            self.filter_boxes[name] = box
            variable.trace_add('write', lambda *_: self.refresh_catalogue())
            self.filters[name] = variable
        for variable in (self.query, self.category, self.sort):
            variable.trace_add('write', lambda *_: self.refresh_catalogue())
        self.listbox = tk.Listbox(self, height=4, bg=t.CONTROL, fg=t.TEXT, selectbackground=t.LINE,
                                  exportselection=False, activestyle='none')
        self.listbox.pack(fill='both', expand=True, padx=12)
        self.listbox.bind('<<ListboxSelect>>', self.describe_voice)
        self.detail = t.label(self, '', 9, t.MUTED, wraplength=850, justify='left')
        self.detail.pack(fill='x', padx=12, pady=4)
        row = tk.Frame(self, bg=t.BG)
        row.pack(fill='x', padx=12)
        button(row, '★ FAVOURITE', self.favourite, padx=8).pack(side='left')
        button(row, 'IMPORT VOICE MANIFEST', self.import_model, padx=8).pack(side='left', padx=5)
        t.label(row, 'Voice labels describe presentation. Unspecified metadata stays unclassified.', 9, t.MUTED).pack(side='left')
        controls = tk.Frame(self, bg=t.BG)
        controls.pack(fill='x', padx=12, pady=5)
        for index, (key, low, high, step) in enumerate([('speed', .5, 2, .05), ('pitch', -12, 12, .5),
                                                       ('volume', 0, 2, .05), ('mix', 0, 1, .05)]):
            unit = ' ×' if key == 'speed' else ' semitones' if key == 'pitch' else ''
            t.label(controls, key.title() + unit, 9).grid(row=0, column=index)
            tk.Scale(controls, variable=self.values[key], from_=low, to=high, resolution=step,
                     orient='horizontal', bg=t.BG, fg=t.TEXT, troughcolor=t.CONTROL,
                     highlightthickness=0, length=185).grid(row=1, column=index, sticky='ew')
            controls.columnconfigure(index, weight=1)
        options = tk.Frame(self, bg=t.BG)
        options.pack(fill='x', padx=12)
        for key, label in [('normalize', 'Normalise'), ('denoise', 'Noise reduction'), ('trim_edges', 'Trim silent edges only')]:
            tk.Checkbutton(options, text=label, variable=self.flags[key], bg=t.BG, fg=t.TEXT,
                           selectcolor=t.CONTROL).pack(side='left')
        button(options, 'RESET', self.reset, padx=8).pack(side='right')
        actions = tk.Frame(self, bg=t.BG)
        actions.pack(fill='x', padx=12, pady=6)
        for label, callback in [('TRANSFORM · LOCAL', self.convert), ('PREVIEW SETTINGS', self.preview_settings),
                                ('A · ORIGINAL', lambda: self.play(self.original)),
                                ('B · RESULT', lambda: self.play(self.output)), ('SAVE AS', self.save_as),
                                ('CANCEL', self.cancel.set)]:
            button(actions, label, callback, accent=label.startswith('TRANSFORM'), padx=8).pack(side='left', padx=2)
        timeline = tk.Frame(self, bg=t.PANEL)
        timeline.pack(fill='x', padx=12, pady=4)
        for label, variable in [('Start (output s)', self.start), ('Voice volume', self.track_volume), ('Background gain', self.duck)]:
            t.label(timeline, label, 9).pack(side='left', padx=4)
            tk.Entry(timeline, textvariable=variable, width=6).pack(side='left')
        for label, callback in [('AT PLAYHEAD', self.at_playhead), ('ADD / REPLACE', self.attach), ('REMOVE', self.remove)]:
            button(timeline, label, callback, padx=7).pack(side='left', padx=3)
        self.status = t.label(self, 'Local conversion ready.' if available() else 'Local conversion not installed. Run setup-voice-studio.py once; recordings work independently.',
                              9, t.MUTED, wraplength=850, justify='left')
        self.status.pack(fill='x', padx=12, pady=6)

    def background(self, callback, message):
        if self.busy or self.recorder.active:
            return
        self.busy = True
        self.cancel.clear()
        self.status.configure(text=message, fg=t.CYAN)
        def worker():
            try:
                self.events.put(('done', callback()))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def load_devices(self):
        return ('devices', microphones())

    def settings(self):
        return VoiceSettings(**{key: value.get() for key, value in self.values.items()},
                             **{key: value.get() for key, value in self.flags.items()})

    def ffmpeg(self):
        backend = getattr(self.studio.master, 'backend', None)
        value = getattr(backend, 'ffmpeg', None) or shutil.which('ffmpeg')
        if not value:
            raise ValueError('FFmpeg is required for voice processing.')
        return value

    def record(self):
        if self.busy or self.recorder.active:
            return
        try:
            index = self.device_box.current()
            if index < 0:
                raise ValueError('Select a microphone first.')
            self.recorder.start(self.devices[index]['index'])
            self.status.configure(text='Recording microphone only. STOP saves this original take.', fg=t.RED)
        except Exception as exc:
            self.status.configure(text=str(exc), fg=t.RED)

    def import_recording(self):
        if self.busy or self.recorder.active:
            return
        path = filedialog.askopenfilename(parent=self, title='Import narration', filetypes=[('Audio', '*.wav *.mp3 *.flac *.m4a *.ogg')])
        if path:
            try:
                ffmpeg = self.ffmpeg()
                self.background(lambda: ('original', import_audio(path, ffmpeg)), 'Preserving and importing recording…')
            except Exception as exc:
                self.status.configure(text=str(exc), fg=t.RED)

    def selected(self):
        selection = self.listbox.curselection()
        return self.visible[selection[0]] if selection else None

    def refresh_catalogue(self):
        previous = self.selected() if self.visible else None
        for key, box in self.filter_boxes.items():
            box['values'] = ('All',) + tuple(sorted({getattr(v, key) for v in self.catalogue.voices()}))
        self.visible = self.catalogue.search(self.query.get(), self.category.get(), self.favourites.get(),
                                             self.sort.get(), **{key: var.get() for key, var in self.filters.items()})
        self.listbox.delete(0, 'end')
        for voice in self.visible:
            star = '★ ' if voice.id in self.catalogue.state['favourites'] else ''
            self.listbox.insert('end', star + voice.name + ('   · INSTALLED' if voice.installed else '   · NOT INSTALLED'))
        if self.visible:
            selected = next((i for i, v in enumerate(self.visible) if previous and v.id == previous.id), 0)
            self.listbox.selection_set(selected)
            self.describe_voice()
        else:
            self.detail.configure(text='No matching voices. Unclassified stock voices are not assigned a gender or age.')

    def describe_voice(self, _event=None):
        voice = self.selected()
        if voice:
            self.detail.configure(text=f'{voice.provider} · {voice.id} · {voice.mode} · {voice.cost}\n{voice.provenance}')

    def favourite(self):
        if voice := self.selected():
            try:
                self.catalogue.favourite(voice.id)
                self.refresh_catalogue()
            except OSError as exc:
                self.status.configure(text=f'Could not save favourites: {exc}', fg=t.RED)

    def import_model(self):
        if self.busy or self.recorder.active:
            return
        path = filedialog.askopenfilename(parent=self, title='Import permitted OpenVoice speaker manifest', filetypes=[('Voice manifest', '*.json')])
        if path:
            self.background(lambda: ('catalogue', self.catalogue.import_voice(path)), 'Validating speaker permissions and model format…')

    def convert(self):
        voice = self.selected()
        if not self.original or not voice:
            self.status.configure(text='Record/import narration and select a voice first.', fg=t.RED)
            return
        try:
            settings, ffmpeg, original = self.settings(), self.ffmpeg(), self.original
            settings.validate()
            def work():
                path = convert_voice(original, voice.model, ffmpeg, settings, cancel=self.cancel)
                self.catalogue.used(voice.id)
                return ('converted', path)
            self.background(work, 'Converting the original performance locally…')
        except Exception as exc:
            self.status.configure(text=str(exc), fg=t.RED)

    def preview_settings(self):
        if self.converted:
            self.convert()
            return
        if self.original:
            try:
                source, ffmpeg, settings = self.original, self.ffmpeg(), self.settings()
                settings.validate()
                self.background(lambda: ('output', process_voice(source, ffmpeg, settings)),
                                'Rendering a separate settings preview…')
            except Exception as exc:
                self.status.configure(text=str(exc), fg=t.RED)

    def reset(self):
        for key, variable in self.values.items():
            variable.set(0 if key == 'pitch' else 1)
        for variable in self.flags.values():
            variable.set(False)

    def play(self, path):
        if path and not self.recorder.active:
            try:
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as exc:
                self.status.configure(text=str(exc), fg=t.RED)

    def save_as(self):
        if self.output:
            target = filedialog.asksaveasfilename(parent=self, defaultextension='.wav', filetypes=[('WAV audio', '*.wav')])
            if target:
                try:
                    with self.output.open('rb') as src, Path(target).open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                    self.status.configure(text='Saved a separate WAV copy.', fg=t.GREEN)
                except OSError as exc:
                    self.status.configure(text=f'Could not save: {exc}. Choose a new, writable filename.', fg=t.RED)

    def at_playhead(self):
        editor = self.studio.master
        if getattr(editor, 'trim', None):
            self.start.set(round(editor.cuts.source_elapsed(editor.position, editor.trim) / editor.edits.speed, 3))

    def attach(self):
        editor = self.studio.master
        if not self.output or not getattr(editor, 'media', None):
            return
        try:
            cue = Narration(str(self.output), self.start.get(), self.track_volume.get(), self.duck.get())
            cue.validate(editor.edits.output_duration(editor.cuts.kept_duration(editor.trim)))
            editor.stop_play()
            editor.edits = replace(editor.edits, narration=cue)
            editor.request_frame()
            self.status.configure(text=f'Narration placed at output {cue.start:.3f}s. Preview and export use the same audio.', fg=t.GREEN)
        except Exception as exc:
            self.status.configure(text=str(exc), fg=t.RED)

    def remove(self):
        editor = self.studio.master
        if getattr(editor, 'edits', None):
            editor.stop_play()
            editor.edits = replace(editor.edits, narration=None)
            editor.request_frame()
            self.status.configure(text='Removed timeline narration. Saved audio remains in the library.', fg=t.MUTED)

    def draw_wave(self):
        self.wave.delete('all')
        width, height = self.wave.winfo_width(), self.wave.winfo_height()
        for i, value in enumerate(self.wave_points):
            x = i * width / max(1, len(self.wave_points))
            self.wave.create_line(x, height/2-value*height*.45, x, height/2+value*height*.45, fill=t.CYAN)

    def show_audio(self, kind, path):
        path = Path(path)
        if kind == 'original':
            self.original, self.converted = path, None
        if kind == 'converted':
            self.converted = path
        self.output = path
        info = wav_info(path)
        self.wave_points = waveform(path)
        self.draw_wave()
        self.take_info.configure(text=f'{info["duration"]:.2f} seconds · {info["bytes"]:,} bytes · {path.name}')
        self.status.configure(text='Saved locally. Compare A/B, SAVE AS or ADD / REPLACE on the output timeline.', fg=t.GREEN)

    def poll(self):
        self.meter['value'] = self.recorder.level
        if self.recorder.active:
            seconds = self.recorder.frames / self.recorder.rate
            self.take_info.configure(text=f'{"PAUSED" if self.recorder.paused.is_set() else "RECORDING"} · {seconds:.2f}s · {44+self.recorder.frames*2:,} bytes')
        for queue in (self.events, self.recorder.events):
            try:
                while True:
                    kind, value = queue.get_nowait()
                    if queue is self.events:
                        self.busy = False
                    if kind == 'error':
                        self.status.configure(text=value, fg=t.RED)
                    elif kind == 'saved':
                        self.show_audio('original', value)
                    elif kind == 'done':
                        action, payload = value
                        if action == 'devices':
                            self.devices = payload
                            self.device_box['values'] = [f'{d["index"]}: {d["name"]}' for d in payload]
                            if payload:
                                self.device_box.current(0)
                            self.status.configure(text='Microphone ready. Nothing is recorded until you press RECORD.', fg=t.MUTED)
                        elif action == 'catalogue':
                            self.refresh_catalogue()
                        else:
                            self.show_audio(action, payload)
            except Empty:
                pass
        self.timer = self.after(80, self.poll)

    def close(self):
        self.cancel.set()
        self.recorder.stop()
        if self.recorder.worker:
            self.recorder.worker.join(timeout=2)
        self.after_cancel(self.timer)
        try:
            import winsound
            winsound.PlaySound(None, 0)
        except ImportError:
            pass
