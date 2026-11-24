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

    def _build(self):
        heading = tk.Frame(self, bg=t.BG)
        heading.pack(fill='x', padx=16, pady=(12, 6))
        t.label(heading, '🎙  COMMENTARY STUDIO', 17, t.CYAN, True).pack(side='left')
        self.record_hint = t.label(
            heading, 'Record locally · originals never overwritten', 9, t.MUTED)
        self.record_hint.pack(side='right')
        record = tk.Frame(self, bg=t.PANEL)
        record.pack(fill='x', padx=16, pady=4)
        t.label(record, 'MIC', 9, t.MUTED, True).pack(side='left', padx=7)
        self.device_picker = ttk.Combobox(
            record, values=(), textvariable=self.mic, state='readonly', width=27)
        self.device_picker.pack(side='left', padx=4, pady=7)
        self.record_button = self._button(record, '● RECORD + PLAY', self.record, True)
        self.stop_button = self._button(record, '■ STOP & SAVE', self.stop)
        self.stop_button.configure(state='disabled')
        self.reload_mics_button = self._button(record, '↻', self.reload_mics)
        self.level_meter = ttk.Progressbar(self, maximum=1.0)
        self.level_meter.pack(fill='x', padx=20, pady=(1, 6))
        t.label(self, 'Use headphones to avoid recording gameplay sound through the mic. The video starts when microphone capture is ready.',
                9, t.MUTED).pack(anchor='w', padx=18)

        clip_head = tk.Frame(self, bg=t.BG)
        clip_head.pack(fill='x', padx=18, pady=(11, 3))
        t.label(clip_head, 'VOICE TIMELINE · RECORDINGS', 10, t.CYAN, True).pack(side='left')
        t.label(clip_head, 'Select a take to edit, split or convert', 9, t.MUTED).pack(side='right')
        holder = tk.Frame(self, bg=t.BG)
        holder.pack(fill='x', padx=18)
        self.clips = tk.Listbox(
            holder, height=4, bg=t.CONTROL, fg=t.TEXT,
            selectbackground=t.LINE, activestyle='none',
            exportselection=False)
        self.clips.pack(side='left', fill='both', expand=True)
        self.clips.bind('<<ListboxSelect>>', self.on_select)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=self.clips.yview)
        scroll.pack(side='right', fill='y')
        self.clips.configure(yscrollcommand=scroll.set)

        self.wave = tk.Canvas(self, height=63, bg=t.PANEL, highlightthickness=0)
        self.wave.pack(fill='x', padx=18, pady=(5, 5))
        self.wave.bind('<Configure>', lambda _: self.draw_wave())
        fields = tk.Frame(self, bg=t.BG)
        fields.pack(fill='x', padx=16, pady=(2, 5))
        values = [('START',self.start_var),('END',self.end_var),
                  ('SOURCE IN',self.source_var),('VOICE LEVEL',self.volume_var),
                  ('GAME LEVEL',self.background_var),('FADE IN',self.fadein_var),
                  ('FADE OUT',self.fadeout_var)]
        for index, (label, var) in enumerate(values):
            group = tk.Frame(fields, bg=t.BG)
            group.grid(row=index//4, column=index%4, sticky='ew', padx=3, pady=2)
            fields.columnconfigure(index%4, weight=1)
            t.label(group, label, 8, t.MUTED, True).pack(anchor='w')
            tk.Entry(group, textvariable=var, width=8, bg=t.CONTROL, fg=t.TEXT,
                     insertbackground=t.CYAN, relief='flat').pack(fill='x', ipady=4)
        edit = tk.Frame(self, bg=t.BG)
        edit.pack(fill='x', padx=18, pady=(3, 8))
        self.apply_button = self._button(edit,'APPLY EDIT',self.apply)
        self.split_button = self._button(edit,'SPLIT AT PLAYHEAD',self.split)
        self.seek_button = self._button(edit,'JUMP TO CLIP',self.seek)
        self.delete_button = self._button(edit,'DELETE FROM VIDEO',self.remove)
        self.original_button = self._button(edit,'USE ORIGINAL VOICE',self.use_original)

        convert_header = tk.Frame(self, bg=t.BG)
        convert_header.pack(fill='x', padx=18, pady=(2, 5))
        t.label(convert_header, 'VOICE ALTERNATOR · LOCAL', 10, t.CYAN, True).pack(side='left')
        self.voice_picker = ttk.Combobox(
            convert_header, textvariable=self.voice_var, state='readonly',
            values=(), width=27)
        self.voice_picker.pack(side='right')
        knobs = tk.Frame(self, bg=t.PANEL)
        knobs.pack(fill='x', padx=18)
        for index, (title, var, low, high, step) in enumerate(
                (('PITCH',self.pitch_var,-12,12,.5),
                 ('SPEED',self.speed_var,.5,2,.05),
                 ('VOICE MIX',self.mix_var,0,1,.05))):
            block = tk.Frame(knobs, bg=t.PANEL)
            block.grid(row=0, column=index, sticky='ew', padx=8, pady=4)
            knobs.columnconfigure(index,weight=1)
            t.label(block,title,9,t.MUTED,True).pack(anchor='w')
            tk.Scale(block,variable=var,from_=low,to=high,resolution=step,
                     orient='horizontal',bg=t.PANEL,fg=t.TEXT,
                     troughcolor=t.CONTROL,highlightthickness=0,
                     length=175).pack(fill='x')
        controls = tk.Frame(self, bg=t.BG)
        controls.pack(fill='x', padx=18, pady=(7, 2))
        self.convert_button = self._button(controls,'CONVERT · OPENVOICE',self.convert,True)
        self.process_button = self._button(controls,'PITCH / SPEED ONLY',self.process)
        self.listen_original_button = self._button(controls,'▶ ORIGINAL',lambda:self.listen('original'))
        self.listen_result_button = self._button(controls,'▶ CURRENT',lambda:self.listen('current'))
        self.cancel_button = self._button(controls,'CANCEL PROCESS',self._cancel.set)
        self.status = t.label(
            self, 'Preparing microphone…', 9, t.MUTED,
            anchor='w', justify='left', wraplength=770)
        self.status.pack(fill='x', padx=18, pady=(5, 6))

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
            self._task(self._load_mics, 'Looking for microphones…')

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
            self.draw_wave()

    def on_select(self, _event=None):
        index = self.clips.curselection()
        if not index:
            return
        idx = index[0]
        cues = self.editor.edits.commentary_clips
        if not 0 <= idx < len(cues):
            return
        self._selected = idx
        cue = cues[idx]
        for var,value in ((self.start_var,cue.start),(self.end_var,cue.end),
                          (self.source_var,cue.source_in),(self.volume_var,cue.volume),
                          (self.background_var,cue.background_gain),
                          (self.fadein_var,cue.fade_in),(self.fadeout_var,cue.fade_out)):
            var.set(f'{value:.3f}')
        self.draw_wave()

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
        width = max(10, self.wave.winfo_width()-16)
        height = self.wave.winfo_height()
        try:
            info = wav_info(cue.file)
            if info['duration'] > 240:
                self.wave.create_text(12,31,text='Long recording · trim using the time controls.',
                                      fill=t.MUTED,anchor='w')
                return
            points = waveform(cue.file, min(300, width//3))
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
        self.wave.create_text(8,7,text='Current voice waveform · original remains saved',
                              anchor='w',fill=t.MUTED,font=(t.FONT,-8))

    def _commit(self, cues, select=None):
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
        editor = self.editor
        if self._busy or self.recorder.active:
            return
        if not editor.media or not editor.trim or editor.exporter.busy or editor.closing:
            self.message('Open a video before recording commentary.',True)
            return
        pos = self.device_picker.current()
        if pos < 0 or pos >= len(self.devices):
            self.message('Select a microphone. If none is listed, install requirements-audio.txt.',True)
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
        for button in (self.convert_button,self.process_button,self.record_button,
                       self.apply_button,self.split_button,self.delete_button,
                       self.original_button):
            button.configure(state='disabled' if busy else 'normal')

    def listen(self, which):
        idx=self.chosen()
        if idx is None:
            return
        cue=self.editor.edits.commentary_clips[idx]
        path=cue.original_file or cue.file if which=='original' else cue.file
        try:
            import winsound
            winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC)
        except (ImportError,OSError,RuntimeError) as exc:
            self.message(f'Could not play WAV: {exc}',True)

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
                if error:
                    self.message(error,True)
                elif value[0]=='devices':
                    self.devices=value[1]
                    self.device_picker.configure(values=[
                        f"{d['name'][:38]}  #{d['index']}" for d in self.devices])
                    if self.devices:self.device_picker.current(0)
                    else:self.message('No microphone found. Connect one and choose ↻.',True)
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
        self._poll_id=self.after(80,self.poll)

    def close(self):
        self._closing=True
        self._cancel.set()
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
        try:
            import winsound
            winsound.PlaySound(None,0)
        except (ImportError,OSError,RuntimeError):
            pass
        self.destroy()
        if getattr(self.editor,'commentary_studio',None) is self:
            self.editor.commentary_studio=None
