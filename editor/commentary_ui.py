"""Direct, local microphone commentary workstation for Quick Edit.

The capture plays beside the video, stays on the output clock and can be
split/trimmed/moved after saving. Existing OpenVoice V2 runtime is optional.
No API calls, auto downloads, overwrites or background recording on open.
"""
from dataclasses import replace
from pathlib import Path
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import ttk

from ui import theme as t
from .commentary import CommentaryClip, split_clip, validate_commentary
from .edit_history import EditHistory, EditSnapshot
from .voice_assets import VoiceSettings, process_voice, wav_info, waveform
from .voice_catalogue import Catalogue
from .voice_conversion import available, convert_voice, MODEL_URL
from .voice_recording import MicrophoneRecorder, microphones
from .commentary_playback import TakePlayback


class CommentaryStudio(tk.Toplevel):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.title('PULSE // COMMENTARY STUDIO')
        self.configure(bg=t.BG)
        self.geometry('830x675')
        self.minsize(675, 575)
        self.transient(editor)
        # No grab: the user must be able to watch/scrub the parent video.
        self.events = Queue()
        self.recorder = MicrophoneRecorder()
        self.player = TakePlayback()
        self._pending_play = None
        self.catalogue = Catalogue()
        self.devices = []
        self.voices = []
        self._selected = None
        self._recording_playhead = None
        self._video_started = False
        self._busy = False
        self._closing = False
        self._cancel = threading.Event()
        self._poll_id = None
        self._hud = None
        self._hud_level = None
        self._hud_status = None
        self.mic = tk.StringVar(value='')
        self.start_var = tk.StringVar(value='0')
        self.end_var = tk.StringVar(value='0')
        self.source_var = tk.StringVar(value='0')
        self.volume_var = tk.StringVar(value='1')
        self.background_var = tk.StringVar(value='.50')
        self.fadein_var = tk.StringVar(value='.025')
        self.fadeout_var = tk.StringVar(value='.045')
        self.voice_var = tk.StringVar(value='')
        self.pitch_var = tk.DoubleVar(value=0.)
        self.speed_var = tk.DoubleVar(value=1.)
        self.mix_var = tk.DoubleVar(value=1.)
        self.audition_var = tk.StringVar(value='current')
        self.status_bar = tk.Frame(self, bg=t.BG)
        self.status_bar.pack(side='bottom', fill='x', padx=17, pady=(4, 9))
        # Scroll the studio vertically on smaller Windows laptops; never
        # clip the bottom Convert/Cancel controls behind an oversized dialog.
        self.view = tk.Canvas(self, bg=t.BG, bd=0, highlightthickness=0)
        self.view.pack(side='left', fill='both', expand=True)
        self.view_scroll = ttk.Scrollbar(self, orient='vertical', command=self.view.yview)
        self.view_scroll.pack(side='right', fill='y')
        self.view.configure(yscrollcommand=self.view_scroll.set)
        self.content = tk.Frame(self.view, bg=t.BG)
        self._content_id = self.view.create_window(0, 0, window=self.content, anchor='nw')
        self.content.bind('<Configure>', self._content_resized)
        self.view.bind('<Configure>', self._viewport_resized)
        self.bind('<MouseWheel>', self._wheel)
        self._build()
        self.load_voices()
        self.refresh()
        self._task(self._load_mics, 'Looking for microphones…')
        self._poll_id = self.after(80, self.poll)
        self.protocol('WM_DELETE_WINDOW', self.close)

    def _button(self, parent, label, callback, accent=False):
        widget = t.button(parent, label, callback, accent=accent)
        widget.configure(padx=8, pady=5, font=(t.FONT, -9, 'bold'))
        widget.pack(side='left', padx=(0, 5))
        return widget

    def _content_resized(self, _event=None):
        self.view.configure(scrollregion=self.view.bbox('all'))

    def _viewport_resized(self, event):
        self.view.itemconfigure(self._content_id, width=max(1, event.width))

    def _wheel(self, event):
        if not self._closing:
            self.view.yview_scroll(-1 if event.delta > 0 else 1,'units')

    def _build(self):
        heading = tk.Frame(self.content, bg=t.BG)
        heading.pack(fill='x', padx=16, pady=(12, 5))
        t.label(heading, '🎙  COMMENTARY STUDIO', 16, t.CYAN, True).pack(side='left')
        t.label(heading, 'Record · Review · Edit · Convert', 10, t.MUTED).pack(side='right')

        t.label(self.content, '01   RECORD A TAKE', 11, t.CYAN, True).pack(
            anchor='w', padx=19, pady=(8, 4))
        record = tk.Frame(self.content, bg=t.PANEL)
        record.pack(fill='x', padx=16, pady=(0, 4))
        t.label(record, 'MICROPHONE', 10, t.TEXT, True).pack(side='left', padx=(12, 7))
        self.device_picker = ttk.Combobox(
            record, values=(), textvariable=self.mic, state='readonly', width=29)
        self.device_picker.pack(side='left', padx=(0, 8), pady=10)
        self.record_button = self._button(record, '●  RECORD + VIDEO', self.record, True)
        self.record_button.configure(state='disabled', padx=12, pady=9,
                                     font=(t.FONT, -10, 'bold'))
        self.stop_button = self._button(record, '■  STOP & SAVE', self.stop)
        self.stop_button.configure(state='disabled', padx=11, pady=9)
        self.reload_mics_button = self._button(record, '↻ REFRESH', self.reload_mics)
        self.level_meter = ttk.Progressbar(self.content, maximum=1.0)
        self.level_meter.pack(fill='x', padx=20, pady=(1, 2))
        t.label(self.content,
                'Records while your video plays. Headphones prevent speaker sound bleeding into the mic.',
                9, t.MUTED).pack(anchor='w', padx=19, pady=(0, 7))

        clip_head = tk.Frame(self.content, bg=t.BG)
        clip_head.pack(fill='x', padx=18, pady=(8, 5))
        t.label(clip_head, '02   LISTEN & EDIT', 11, t.CYAN, True).pack(side='left')
        t.label(clip_head, 'Choose a take below', 10, t.MUTED).pack(side='right')
        holder = tk.Frame(self.content, bg=t.BG)
        holder.pack(fill='x', padx=18)
        self.clips = tk.Listbox(
            holder, height=3, bg=t.CONTROL, fg=t.TEXT,
            font=(t.FONT, -11), selectbackground=t.LINE,
            activestyle='none', exportselection=False)
        self.clips.pack(side='left', fill='both', expand=True)
        self.clips.bind('<<ListboxSelect>>', self.on_select)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.clips.yview)
        scroll.pack(side='right', fill='y')
        self.clips.configure(yscrollcommand=scroll.set)

        self.wave = tk.Canvas(self.content, height=72, bg=t.PANEL, highlightthickness=0)
        self.wave.pack(fill='x', padx=18, pady=(7, 5))
        self.wave.bind('<Configure>', lambda _: self.draw_wave())

        playback = tk.Frame(self.content, bg=t.PANEL)
        playback.pack(fill='x', padx=18, pady=(0, 3))
        source = tk.Frame(playback, bg=t.PANEL)
        source.pack(fill='x', padx=12, pady=(7, 4))
        t.label(source, 'HEAR', 10, t.TEXT, True).pack(side='left', padx=(0, 10))
        self.audition_choices = t.Segments(
            source, self.audition_var,
            (('current', 'CURRENT VOICE'), ('original', 'ORIGINAL VOICE')),
            self.on_audition_change)
        self.audition_choices.pack(side='left', fill='x', expand=True)
        transport = tk.Frame(playback, bg=t.PANEL)
        transport.pack(fill='x', padx=12, pady=(0, 9))
        self.play_take_button = self._button(
            transport, '▶  PLAY TAKE', self.play_take, True)
        self.pause_take_button = self._button(
            transport, '⏸  PAUSE', self.pause_take)
        self.stop_take_button = self._button(
            transport, '■  STOP', self.stop_take)
        for button in (self.play_take_button, self.pause_take_button,
                       self.stop_take_button):
            button.configure(font=(t.FONT, -12, 'bold'), padx=19, pady=10,
                             state='disabled')
        self.playback_clock = t.label(
            transport, '0:00 / 0:00', 12, t.TEXT, True)
        self.playback_clock.pack(side='right', padx=(8, 2))
        t.label(self.content,
                'These buttons play the selected voice only. Use PLAY in the video editor to hear the full mix.',
                9, t.MUTED).pack(anchor='w', padx=20, pady=(0, 7))

        t.label(self.content, 'EDIT POSITION · SECONDS', 10, t.CYAN, True).pack(
            anchor='w', padx=19, pady=(5, 2))
        timing = tk.Frame(self.content, bg=t.BG)
        timing.pack(fill='x', padx=16)
        self._field(timing, 0, 0, 'START IN VIDEO', self.start_var)
        self._field(timing, 0, 1, 'END IN VIDEO', self.end_var)
        self._field(timing, 0, 2, 'SKIP FROM RECORDING', self.source_var)
        t.label(self.content, 'MIX & FADES', 10, t.CYAN, True).pack(
            anchor='w', padx=19, pady=(8, 2))
        mixing = tk.Frame(self.content, bg=t.BG)
        mixing.pack(fill='x', padx=16)
        self._field(mixing, 0, 0, 'VOICE VOLUME (0–2)', self.volume_var)
        self._field(mixing, 0, 1, 'GAME VOLUME (0–1)', self.background_var)
        self._field(mixing, 0, 2, 'FADE IN (SEC)', self.fadein_var)
        self._field(mixing, 0, 3, 'FADE OUT (SEC)', self.fadeout_var)
        actions = tk.Frame(self.content, bg=t.BG)
        actions.pack(fill='x', padx=18, pady=(9, 10))
        self.apply_button = self._button(actions, '✓  APPLY CHANGES', self.apply, True)
        self.split_button = self._button(actions, '✂  SPLIT AT PLAYHEAD', self.split)
        self.seek_button = self._button(actions, '⌖  GO TO TAKE', self.seek)
        self.delete_button = self._button(actions, '✕  REMOVE FROM VIDEO', self.remove)
        for button in (self.apply_button, self.split_button,
                       self.seek_button, self.delete_button):
            button.configure(font=(t.FONT, -10, 'bold'), padx=11, pady=9)

        t.label(self.content, '03   VOICE ALTERNATOR', 11, t.CYAN, True).pack(
            anchor='w', padx=19, pady=(7, 5))
        convert_header = tk.Frame(self.content, bg=t.PANEL)
        convert_header.pack(fill='x', padx=18)
        t.label(convert_header, 'TARGET VOICE', 10, t.TEXT, True).pack(
            side='left', padx=(10, 9), pady=8)
        self.voice_picker = ttk.Combobox(
            convert_header, textvariable=self.voice_var, state='readonly',
            values=(), width=30)
        self.voice_picker.pack(side='left', fill='x', expand=True, padx=(0, 10), pady=8)
        knobs = tk.Frame(self.content, bg=t.PANEL)
        knobs.pack(fill='x', padx=18, pady=(2, 0))
        for index, (title, var, low, high, step) in enumerate(
                (('PITCH', self.pitch_var, -12, 12, .5),
                 ('SPEED', self.speed_var, .5, 2, .05),
                 ('VOICE MIX', self.mix_var, 0, 1, .05))):
            block = tk.Frame(knobs, bg=t.PANEL)
            block.grid(row=0, column=index, sticky='ew', padx=10, pady=6)
            knobs.columnconfigure(index, weight=1)
            t.label(block, title, 10, t.TEXT, True).pack(anchor='w')
            tk.Scale(block, variable=var, from_=low, to=high, resolution=step,
                     orient='horizontal', bg=t.PANEL, fg=t.TEXT,
                     troughcolor=t.CONTROL, highlightthickness=0,
                     length=170).pack(fill='x')
        controls = tk.Frame(self.content, bg=t.BG)
        controls.pack(fill='x', padx=18, pady=(7, 8))
        self.convert_button = self._button(
            controls, '⚡  CONVERT VOICE', self.convert, True)
        self.process_button = self._button(
            controls, 'PITCH / SPEED ONLY', self.process)
        self.original_button = self._button(
            controls, '↶  RESTORE ORIGINAL', self.use_original)
        self.cancel_button = self._button(
            controls, 'CANCEL PROCESS', self._cancel.set)

        # Persistent status: the user can see errors/results without having to
        # scroll past the voice alternator.
        self.status = t.label(
            self.status_bar, 'Preparing microphone…', 10, t.MUTED,
            anchor='w', justify='left', wraplength=790)
        self.status.pack(fill='x', padx=2)
        self._sync_preview_buttons()

    def _field(self, parent, row, column, title, variable):
        group = tk.Frame(parent, bg=t.BG)
        group.grid(row=row, column=column, sticky='ew', padx=4, pady=3)
        parent.columnconfigure(column, weight=1)
        t.label(group, title, 9, t.TEXT, True).pack(anchor='w', pady=(0, 2))
        tk.Entry(group, textvariable=variable, width=8, bg=t.CONTROL,
                 fg=t.TEXT, insertbackground=t.CYAN, relief='flat',
                 font=(t.FONT, -11)).pack(fill='x', ipady=7)

    def _sync_preview_buttons(self):
        take = self.chosen() is not None
        usable = take and not self.recorder.active and not self._busy
        playing = self.player.active
        paused = self.player.paused
        self.play_take_button.configure(
            state='normal' if usable and (not playing or paused) else 'disabled')
        self.pause_take_button.configure(
            state='normal' if usable and playing else 'disabled',
            text='▶  RESUME' if paused else '⏸  PAUSE')
        self.stop_take_button.configure(
            state='normal' if playing else 'disabled')

    def on_audition_change(self):
        # Changing playback version never alters which file is used on export.
        self.stop_take()
        self.draw_wave()
        self._sync_preview_buttons()

    def play_take(self):
        idx = self.chosen()
        cues = self.editor.edits.commentary_clips
        if idx is None or idx >= len(cues) or self.recorder.active or self._busy:
            self.message('Select a saved take first.', True)
            return
        cue = cues[idx]
        which = self.audition_var.get()
        path = cue.original_file or cue.file if which == 'original' else cue.file
        try:
            info = wav_info(path)
            length = min(cue.duration, info['duration'] - cue.source_in)
            if length <= 0:
                raise ValueError('No voice remains in this edited interval.')
            if self.player.active and self.player.paused:
                # Pause is reversible. Changing take/version stops the previous
                # preview in on_select()/on_audition_change().
                result = self.player.play(path, cue.source_in, length)
            elif self.player.active:
                self.player.stop()
                self._pending_play = (path, cue.source_in, length)
                result = 'switching'
            else:
                result = self.player.play(path, cue.source_in, length)
            self.message(
                ('Finishing previous preview…' if result == 'switching' else
                 ('Resumed' if result == 'resumed' else 'Playing') +
                 f' {which.upper()} voice · audio-only preview.'))
        except (ValueError, OSError) as exc:
            self.message(f'Cannot preview take: {exc}', True)
        self._sync_preview_buttons()

    def pause_take(self):
        if not self.player.active:
            return
        paused = self.player.pause()
        self.message('Take paused.' if paused else 'Take resumed.')
        self._sync_preview_buttons()

    def stop_take(self):
        self._pending_play = None
        self.player.stop()
        self._sync_preview_buttons()
        if not self._closing:
            self.playback_clock.configure(
                text=f'0:00 / {self._clock(self.player.duration)}')

    @staticmethod
    def _clock(seconds):
        value = max(0, round(seconds))
        return f'{int(value // 60)}:{int(value % 60):02d}'

    def message(self, value, error=False):
        if not self._closing:
            self.status.configure(text=value, fg=t.RED if error else t.CYAN)

    def _task(self, fn, message):
        if self._busy:
            return False
        self._busy = True
        self._cancel.clear()
        self.message(message)
        def worker():
            try:
                self.events.put(('task', fn(), None))
            except Exception as exc:
                self.events.put(('task', None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        return True

    @staticmethod
    def _load_mics():
        return 'devices', microphones()

    def reload_mics(self):
        if not self.recorder.active:
            if self._task(self._load_mics, 'Looking for microphones…'):
                self.record_button.configure(state='disabled')

    def load_voices(self):
        self.voices = self.catalogue.search()
        self.voice_picker.configure(values=tuple(v.name for v in self.voices))
        if self.voices and self.voice_var.get() not in [v.name for v in self.voices]:
            self.voice_var.set(self.voices[0].name)

    def chosen(self):
        index = self.clips.curselection()
        return index[0] if index else self._selected

    def refresh(self, select=None):
        previous = select if select is not None else self.chosen()
        cues = self.editor.edits.commentary_clips
        self.clips.delete(0, 'end')
        for i, cue in enumerate(cues):
            mode = 'ALTERED' if cue.file != (cue.original_file or cue.file) else 'ORIGINAL'
            self.clips.insert('end',
                f'{i+1:02d} · {cue.start:.2f}–{cue.end:.2f}s · {cue.title[:23]} · {mode}')
        self._selected = None
        if cues:
            index = min(previous if previous is not None else len(cues)-1, len(cues)-1)
            self.clips.selection_set(index)
            self.clips.see(index)
            self.on_select()
        else:
            self.stop_take()
            self.draw_wave()
            self._sync_preview_buttons()

    def on_select(self, _event=None):
        index = self.clips.curselection()
        if not index:
            return
        idx = index[0]
        cues = self.editor.edits.commentary_clips
        if not 0 <= idx < len(cues):
            return
        if self._selected != idx:
            self.stop_take()
        self._selected = idx
        cue = cues[idx]
        for var,value in ((self.start_var,cue.start),(self.end_var,cue.end),
                          (self.source_var,cue.source_in),(self.volume_var,cue.volume),
                          (self.background_var,cue.background_gain),
                          (self.fadein_var,cue.fade_in),(self.fadeout_var,cue.fade_out)):
            var.set(f'{value:.3f}')
        self.draw_wave()
        self._sync_preview_buttons()

    def draw_wave(self):
        if not self.winfo_exists():
            return
        self.wave.delete('all')
        index = self.chosen()
        cues = self.editor.edits.commentary_clips
        if index is None or not 0 <= index < len(cues):
            self.wave.create_text(12,31,text='Record a take to see its waveform.',
                                  fill=t.MUTED,anchor='w')
            return
        cue = cues[index]
        audition = self.audition_var.get()
        source = cue.original_file or cue.file if audition == 'original' else cue.file
        width = max(10, self.wave.winfo_width()-16)
        height = self.wave.winfo_height()
        try:
            info = wav_info(source)
            if info['duration'] > 240:
                self.wave.create_text(12,31,text='Long recording · trim using the time controls.',
                                      fill=t.MUTED,anchor='w')
                return
            points = waveform(source, min(300, width//3))
        except (OSError, ValueError) as exc:
            self.wave.create_text(12,31,text=str(exc)[:60],fill=t.RED,anchor='w')
            return
        if not points:
            return
        for i,peak in enumerate(points):
            x = 8 + i*width/len(points)
            h = peak*(height*.45)
            self.wave.create_line(x,height/2-h,x,height/2+h,
                                  fill=t.CYAN,width=max(1,width/len(points)))
        self.wave.create_text(8,7,text=f'{audition.upper()} voice waveform · original retained',
                              anchor='w',fill=t.MUTED,font=(t.FONT,-8))

    def _commit(self, cues, select=None):
        self.stop_take()
        editor = self.editor
        if not editor.media or editor.exporter.busy or editor.closing:
            raise ValueError('Open an editable video first.')
        total = editor.edits.output_duration(editor.cuts.kept_duration(editor.trim))
        validate_commentary(cues,total)
        before = EditSnapshot(editor.trim,editor.cuts,editor.edits)
        updated = replace(editor.edits, commentary_clips=tuple(cues))
        updated.validate(editor.media)
        if editor.timeline_history is None or editor.timeline_history.current != before:
            editor.timeline_history = EditHistory(before)
        editor.timeline_history.end()
        editor.timeline_history.record(replace(before,edits=updated))
        editor.stop_play()
        editor.edits = updated
        editor.update_timeline()
        editor.request_frame()
        editor.note.configure(text='Commentary updated. Original WAV preserved.',fg=t.GREEN)
        self.refresh(select)

    def _show_recording_hud(self):
        """Keep gameplay visible while the microphone records in the background."""
        if self._hud is not None and self._hud.winfo_exists():
            return
        hud = tk.Toplevel(self.editor)
        hud.title('PULSE · RECORDING')
        hud.configure(bg=t.PANEL)
        hud.resizable(False, False)
        x = max(0, min(hud.winfo_screenwidth()-340,
                       self.editor.winfo_rootx()+self.editor.winfo_width()-360))
        y = max(0, min(hud.winfo_screenheight()-160,
                       self.editor.winfo_rooty()+55))
        hud.geometry(f'325x135+{x}+{y}')
        hud.transient(self.editor)
        t.label(hud, '🎙  RECORDING COMMENTARY', 11, t.CYAN, True).pack(
            anchor='w', padx=12, pady=(9,3))
        self._hud_status = t.label(
            hud, 'Starting microphone…', 9, t.MUTED)
        self._hud_status.pack(anchor='w', padx=12)
        self._hud_level = ttk.Progressbar(hud, maximum=1.0)
        self._hud_level.pack(fill='x', padx=12, pady=5)
        stop = t.button(hud, '■  STOP & SAVE', self.stop, accent=True)
        stop.configure(padx=10, pady=5, font=(t.FONT,-10,'bold'))
        stop.pack(fill='x', padx=12)
        hud.protocol('WM_DELETE_WINDOW',self.stop)
        self._hud = hud
        self.withdraw()

    def _hide_recording_hud(self):
        hud, self._hud = self._hud, None
        self._hud_level = None
        self._hud_status = None
        if hud is not None and hud.winfo_exists():
            hud.destroy()
        if not self._closing and self.winfo_exists():
            self.deiconify()
            self.lift()

    def record(self):
        self.stop_take()
        editor = self.editor
        if self._busy or self.recorder.active:
            return
        if not editor.media or not editor.trim or editor.exporter.busy or editor.closing:
            self.message('Open a video before recording commentary.',True)
            return
        pos = self.device_picker.current()
        if pos < 0 or pos >= len(self.devices):
            self.message(
                'No recording input selected. Check Windows Settings → System → Sound → Input; '
                'connect a microphone and press REFRESH. If Windows lists a mic but Pulse does not, '
                'check that PyAudioWPatch is installed.', True)
            return
        at = editor.cuts.source_elapsed(editor.position,editor.trim)/editor.edits.speed
        total = editor.edits.output_duration(editor.cuts.kept_duration(editor.trim))
        if at >= total-.06:
            self.message('Move the playhead earlier in the video.',True)
            return
        try:
            editor.stop_play()
            self._recording_playhead = at
            self._video_started = False
            self.recorder.start(self.devices[pos]['index'])
            self._show_recording_hud()
            self.record_button.configure(state='disabled')
            self.stop_button.configure(state='normal')
            self.message('Opening microphone… video starts when recording is ready.')
        except Exception as exc:
            self.message(str(exc),True)

    def stop(self):
        if self.recorder.active:
            self.recorder.stop()
            self.message('Finishing WAV… original will be kept.')
            if self._hud_status is not None:
                self._hud_status.configure(text='Saving original WAV…',fg=t.CYAN)
        if self._video_started:
            self.editor.stop_play()

    def _record_saved(self, path):
        self.record_button.configure(state='normal')
        self.stop_button.configure(state='disabled')
        if not self._video_started or self._recording_playhead is None:
            self.message('Original WAV saved. Recording did not start video; retry for sync.',True)
            return
        try:
            duration = wav_info(path)['duration']
            # Continuous preview resets play_started when its first frame is
            # actually displayed. Discard any mic pre-roll, not user speech.
            ahead = max(0., getattr(self.editor,'play_started',0)-self.recorder.started_at)
            skip = max(0., min(ahead, duration-.06))
            at = self._recording_playhead
            total = self.editor.edits.output_duration(
                self.editor.cuts.kept_duration(self.editor.trim))
            length = min(duration-skip, total-at)
            if length < .06:
                raise ValueError('Take is too short for the remaining video.')
            cue = CommentaryClip(str(path),at,at+length,source_in=skip,
                                 original_file=str(path))
            self._commit((*self.editor.edits.commentary_clips,cue),
                         len(self.editor.edits.commentary_clips))
            self.message(f'Take saved on VOICE timeline at {at:.2f}s. Edit or convert it below.')
        except Exception as exc:
            self.message(f'Original saved at {path}. Could not attach: {exc}',True)
        finally:
            self._video_started = False
            self._recording_playhead = None

    def apply(self):
        idx=self.chosen()
        if idx is None:
            return
        cues=list(self.editor.edits.commentary_clips)
        cue=cues[idx]
        try:
            cues[idx]=replace(
                cue,start=float(self.start_var.get()),end=float(self.end_var.get()),
                source_in=float(self.source_var.get()),
                volume=float(self.volume_var.get()),
                background_gain=float(self.background_var.get()),
                fade_in=float(self.fadein_var.get()),fade_out=float(self.fadeout_var.get()))
            self._commit(cues,idx)
            self.message('Commentary edit applied. Ctrl+Z restores the previous settings.')
        except (ValueError,IndexError) as exc:
            self.message(str(exc),True)

    def split(self):
        idx=self.chosen()
        if idx is None:
            return
        cues=list(self.editor.edits.commentary_clips)
        cue=cues[idx]
        at=self.editor.cuts.source_elapsed(
            self.editor.position,self.editor.trim)/self.editor.edits.speed
        try:
            left,right=split_clip(cue,at)
            cues[idx:idx+1]=[left,right]
            self._commit(cues,idx+1)
            self.message('Commentary split. Drag/trim either VOICE block separately.')
        except ValueError as exc:
            self.message(str(exc),True)

    def seek(self):
        idx=self.chosen()
        if idx is None:
            return
        cue=self.editor.edits.commentary_clips[idx]
        self.editor.seek_output_time(cue.start)

    def remove(self):
        idx=self.chosen()
        if idx is None:
            return
        cues=list(self.editor.edits.commentary_clips)
        cues.pop(idx)
        try:
            self._commit(cues,max(0,idx-1))
            self.message('Clip removed from video. WAV kept in the private library.')
        except ValueError as exc:
            self.message(str(exc),True)

    def use_original(self):
        idx=self.chosen()
        if idx is None:
            return
        cues=list(self.editor.edits.commentary_clips)
        cue=cues[idx]
        try:
            cues[idx]=cue.with_file(cue.original_file or cue.file)
            self._commit(cues,idx)
            self.message('Original voice restored; converted WAV remains saved.')
        except ValueError as exc:
            self.message(str(exc),True)

    def _selected_voice(self):
        selected=next((v for v in self.voices if v.name==self.voice_var.get()),None)
        if selected is None:
            raise ValueError('Choose a voice from the Voice Alternator.')
        if not selected.installed:
            raise ValueError('This voice is not installed. Set up OpenVoice locally before conversion.')
        return selected

    def _voice_settings(self):
        return VoiceSettings(speed=self.speed_var.get(),pitch=self.pitch_var.get(),
                             volume=1.,mix=self.mix_var.get())

    def _transform(self, method):
        self.stop_take()
        idx=self.chosen()
        if idx is None or self.recorder.active or self._busy:
            return
        cues=self.editor.edits.commentary_clips
        if not 0<=idx<len(cues):
            return
        cue=cues[idx]
        try:
            settings=self._voice_settings()
            settings.validate()
            voice=self._selected_voice() if method=='convert' else None
            ffmpeg=self.editor.backend.ffmpeg
            original=Path(cue.original_file or cue.file)
        except (ValueError,AttributeError) as exc:
            self.message(str(exc),True)
            return
        def work():
            if method=='convert':
                path=convert_voice(original,voice.model,ffmpeg,settings,cancel=self._cancel)
                return ('altered',idx,cue,path,voice.id)
            path=process_voice(original,ffmpeg,settings)
            return ('altered',idx,cue,path,None)
        self._task(work,'Converting locally… source take remains untouched.')
        self._set_processing_buttons(True)

    def convert(self):
        self._transform('convert')

    def process(self):
        self._transform('process')

    def _set_processing_buttons(self,busy):
        for button in (self.convert_button, self.process_button,
                       self.apply_button, self.split_button, self.delete_button,
                       self.original_button):
            button.configure(state='disabled' if busy else 'normal')
        self.record_button.configure(
            state='disabled' if busy or not self.devices or self.recorder.active
            else 'normal')
        self._sync_preview_buttons()

    def listen(self, which):
        # Legacy callbacks now use the same genuine transport.
        if which not in ('current', 'original'):
            raise ValueError('Unknown audition version.')
        self.audition_var.set(which)
        self.play_take()

    def poll(self):
        if self._closing:
            return
        while True:
            try:
                kind, value, error=self.events.get_nowait()
            except Empty:
                break
            if kind=='task':
                self._busy=False
                self._set_processing_buttons(False)
                self.record_button.configure(
                    state='normal' if self.devices else 'disabled')
                if error:
                    hint = ('Microphone support is not installed. Run '
                            'py -3.13 -m pip install -r requirements-audio.txt '
                            'from the Pulse-Capture folder, then reopen Commentary Studio.'
                            if 'pyaudiowpatch' in error.lower() else error)
                    self.message(hint,True)
                elif value[0]=='devices':
                    self.devices=value[1]
                    self.device_picker.configure(values=[
                        f"{d['name'][:38]}  #{d['index']}" for d in self.devices])
                    if self.devices:
                        self.device_picker.current(0)
                        self.record_button.configure(state='normal')
                        # Windows' generic mapping uses the user's DEFAULT
                        # input device and may be the only exposed microphone.
                        names = tuple(d['name'].casefold() for d in self.devices)
                        if all(('sound mapper' in n or
                                'primary sound capture' in n) for n in names):
                            self.message(
                                'Windows default recording input found. In Windows Sound → Input, '
                                'make sure the default device is your microphone.', False)
                        else:
                            self.message(f'{len(self.devices)} recording input(s) found. Choose one and press RECORD.', False)
                    else:
                        self.record_button.configure(state='disabled')
                        self.message(
                            'No microphone input detected. Check Windows Settings → System → Sound → Input, '
                            'microphone privacy permissions and physical connection, then press REFRESH.', True)
                elif value[0]=='altered':
                    _,idx,old,path,voice_id=value
                    try:
                        cues=list(self.editor.edits.commentary_clips)
                        if idx >= len(cues) or cues[idx]!=old:
                            raise ValueError('Clip changed during conversion. The new WAV was saved but not attached.')
                        cues[idx]=old.with_file(path)
                        self._commit(cues,idx)
                        if voice_id:
                            self.catalogue.used(voice_id)
                        self.message('Voice processed and linked. Use ORIGINAL VOICE to revert.')
                    except Exception as exc:
                        self.message(f'Processed WAV saved at {path}; attachment blocked: {exc}',True)
            elif kind=='error':
                self.message(error or str(value),True)
        while True:
            try:
                result=self.recorder.events.get_nowait()
            except Empty:
                break
            kind=result[0]
            if kind=='started':
                try:
                    if self._hud_status is not None:
                        self._hud_status.configure(text='Speak while your video plays',fg=t.CYAN)
                    self.editor.play_preview()
                    self._video_started=bool(self.editor.playing)
                    self.message('Recording microphone and playing video. Press STOP & SAVE to finish.')
                except Exception as exc:
                    self.recorder.stop()
                    self.message(f'Microphone started but video could not play: {exc}',True)
            elif kind=='saved':
                self.editor.stop_play()
                self._hide_recording_hud()
                self._record_saved(result[1])
            elif kind=='error':
                self._hide_recording_hud()
                self.record_button.configure(state='normal')
                self.stop_button.configure(state='disabled')
                self.editor.stop_play()
                self.message(result[1],True)
        self.level_meter['value']=self.recorder.level if self.recorder.active else 0.
        if self._hud_level is not None:
            self._hud_level['value']=self.recorder.level if self.recorder.active else 0.
        while True:
            try:
                event, session, detail = self.player.events.get_nowait()
            except Empty:
                break
            if session != self.player.session:
                continue
            if event == 'finished':
                self.message('Take playback finished.')
            elif event == 'error':
                self.message(f'Take playback failed: {detail}', True)
        if self._pending_play and not self.player.active and not self.recorder.active:
            args, self._pending_play = self._pending_play, None
            try:
                self.player.play(*args)
                self.message('Playing selected take.')
            except (ValueError, OSError) as exc:
                self.message(f'Cannot play take: {exc}', True)
        self.playback_clock.configure(
            text=f'{self._clock(self.player.position)} / {self._clock(self.player.duration)}')
        self._sync_preview_buttons()
        self._poll_id=self.after(80,self.poll)

    def close(self):
        self._closing=True
        self._cancel.set()
        self.player.close()
        self.recorder.stop()
        if self.recorder.worker and self.recorder.worker.is_alive():
            self.recorder.worker.join(timeout=2)
        if self._hud is not None:
            self._hide_recording_hud()
        if self._video_started:
            self.editor.stop_play()
        if self._poll_id:
            try:self.after_cancel(self._poll_id)
            except tk.TclError:pass
        self.destroy()
        if getattr(self.editor,'commentary_studio',None) is self:
            self.editor.commentary_studio=None
