"""Compact Quick Edit music controls for Pulse originals and user imports."""
from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from ui import theme as t
from .music import Music, TRACKS, IMPORT_LABEL, VOLUME_LEVELS


def _percent(value):
    return f'{round(value * 100)}%'


class MusicTools:
    def __init__(self, window):
        self.window = window
        current = window.edits.music
        self.music_on = tk.BooleanVar(value=current.enabled)
        self.track_choice = tk.StringVar(value=current.track)
        self.music_volume = tk.StringVar(value=_percent(current.music_volume))
        self.original_volume = tk.StringVar(value=_percent(current.original_volume))
        self.loop = tk.BooleanVar(value=current.loop)
        self.fade_in = tk.BooleanVar(value=current.fade_in)
        self.fade_out = tk.BooleanVar(value=current.fade_out)
        self.imported = current.imported

        panel = window.panels['MUSIC']
        top = tk.Frame(panel, bg=t.PANEL)
        top.pack(fill='x', pady=(0, 5))

        toggle = tk.Frame(top, bg=t.PANEL)
        toggle.pack(side='left', padx=(0, 8))
        self.toggle_segments = window.add_segments(
            toggle, self.music_on, [(False, 'OFF'), (True, 'ON')], self.changed
        )
        for _, button in self.toggle_segments.buttons:
            button.configure(padx=8, pady=3, font=(t.FONT, -10, 'bold'))

        t.label(top, 'TRACK', 8, t.MUTED, True).pack(side='left', padx=(0, 5))
        self.track_combo = ttk.Combobox(
            top, textvariable=self.track_choice, state='readonly',
            values=tuple(TRACKS), width=22,
        )
        self.track_combo.pack(side='left', fill='x', expand=True)
        self.track_combo.bind('<<ComboboxSelected>>', lambda _: self.changed())
        window.controls.append(self.track_combo)

        self.import_button = t.button(top, 'IMPORT MP3 / WAV', self.import_audio)
        self.import_button.configure(padx=8, pady=3, font=(t.FONT, -10, 'bold'))
        self.import_button.pack(side='right', padx=(8, 0))
        window.controls.append(self.import_button)

        middle = tk.Frame(panel, bg=t.PANEL)
        middle.pack(fill='x')
        choices = tuple(_percent(value) for value in VOLUME_LEVELS)
        for label, variable in (
            ('MUSIC', self.music_volume),
            ('ORIGINAL', self.original_volume),
        ):
            group = tk.Frame(middle, bg=t.PANEL)
            group.pack(side='left', padx=(0, 10))
            t.label(group, label, 8, t.MUTED, True).pack(side='left', padx=(0, 4))
            combo = ttk.Combobox(
                group, textvariable=variable, values=choices,
                state='readonly', width=6,
            )
            combo.pack(side='left')
            combo.bind('<<ComboboxSelected>>', lambda _, self=self: self.changed())
            window.controls.append(combo)
            if label == 'MUSIC':
                self.music_volume_combo = combo
            else:
                self.original_volume_combo = combo

        for label, variable in (
            ('LOOP', self.loop),
            ('FADE IN', self.fade_in),
            ('FADE OUT', self.fade_out),
        ):
            check = tk.Checkbutton(
                middle, text=label, variable=variable, command=self.changed,
                bg=t.PANEL, fg=t.TEXT, selectcolor=t.CONTROL,
                activebackground=t.PANEL, activeforeground=t.TEXT,
                disabledforeground=t.MUTED, bd=0, font=(t.FONT, -10, 'bold'),
            )
            check.pack(side='left', padx=(0, 8))
            window.controls.append(check)

        self.hint = t.label(
            panel,
            'Pulse originals are generated locally · no third-party samples.',
            8, t.MUTED, anchor='w',
        )
        self.hint.pack(fill='x', pady=(5, 0))
        self.refresh()

    @staticmethod
    def _volume(text):
        text = str(text).strip()
        if not text.endswith('%'):
            raise ValueError('Choose a valid music volume.')
        value = float(text[:-1]) / 100
        if value not in VOLUME_LEVELS:
            raise ValueError('Choose one of the available volume levels.')
        return value

    def _state(self):
        return Music(
            enabled=self.music_on.get(),
            track=self.track_choice.get(),
            imported=self.imported,
            music_volume=self._volume(self.music_volume.get()),
            original_volume=self._volume(self.original_volume.get()),
            loop=self.loop.get(),
            fade_in=self.fade_in.get(),
            fade_out=self.fade_out.get(),
        )

    def changed(self):
        w = self.window
        if w.exporter.busy or w.closing:
            return
        try:
            music = self._state()
            music.validate()
            w.edits = replace(w.edits, music=music)
            self.refresh()
            if music.enabled:
                if music.track == IMPORT_LABEL:
                    message = f'Music ready · {Path(music.imported).name}'
                else:
                    recipe = TRACKS[music.track]
                    message = f"{music.track} · {recipe['mood']} · {recipe['bpm']} BPM"
                w.note.configure(text=message, fg=t.MUTED)
            else:
                w.note.configure(text='Music off · source audio is unchanged.', fg=t.MUTED)
        except (ValueError, TypeError) as exc:
            self.sync()
            w.note.configure(text=str(exc), fg=t.RED)

    def import_audio(self):
        w = self.window
        if not w.media or w.exporter.busy or w.closing:
            return
        selected = filedialog.askopenfilename(
            parent=w,
            initialdir=str(w.path.parent),
            title='Choose music',
            filetypes=(('Audio', '*.mp3 *.wav'), ('MP3', '*.mp3'), ('WAV', '*.wav')),
        )
        if not selected:
            return
        self.imported = Path(selected)
        self.track_choice.set(IMPORT_LABEL)
        values = list(TRACKS)
        if IMPORT_LABEL not in values:
            values.append(IMPORT_LABEL)
        self.track_combo.configure(values=tuple(values))
        self.music_on.set(True)
        self.changed()

    def sync(self):
        music = self.window.edits.music
        self.music_on.set(music.enabled)
        self.track_choice.set(music.track)
        self.music_volume.set(_percent(music.music_volume))
        self.original_volume.set(_percent(music.original_volume))
        self.loop.set(music.loop)
        self.fade_in.set(music.fade_in)
        self.fade_out.set(music.fade_out)
        self.imported = music.imported
        values = list(TRACKS)
        if music.track == IMPORT_LABEL and music.imported:
            values.append(IMPORT_LABEL)
        self.track_combo.configure(values=tuple(values))

    def refresh(self):
        w = self.window
        if not hasattr(w, 'video'):
            return
        ready = bool(w.media and w.video.enabled and not w.exporter.busy and not w.closing)
        enabled = ready and self.music_on.get()
        self.toggle_segments.enable(ready)
        self.track_combo.configure(state='readonly' if enabled else 'disabled')
        self.import_button.configure(state='normal' if ready else 'disabled')
        self.music_volume_combo.configure(state='readonly' if enabled else 'disabled')
        self.original_volume_combo.configure(state='readonly' if enabled else 'disabled')
        music = w.edits.music
        if music.track == IMPORT_LABEL and music.imported:
            self.hint.configure(text=f'Imported · {Path(music.imported).name} · check your usage rights.')
        elif music.track in TRACKS:
            recipe = TRACKS[music.track]
            self.hint.configure(
                text=f"{music.track} · {recipe['mood']} · {recipe['bpm']} BPM · original Pulse synthesis."
            )
        else:
            self.hint.configure(text='Pulse originals are generated locally · no third-party samples.')
