"""Track library, attribution and audition sheet for the existing Music panel."""
from dataclasses import replace
from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import ttk

from ui import theme as t
from .media_audition import Audition
from .music import IMPORT_LABEL, resolve_music_path
from .music_library import MusicLibrary, LICENCES, description_credit
from .music_mix import input_loops, filters


class MusicDetails(tk.Toplevel):
    def __init__(self, tools):
        super().__init__(tools.window)
        self.tools=tools;self.window=tools.window
        self.closed=self.busy=False
        self.library=MusicLibrary();self.events=Queue()
        self.title('Music library & track details');self.geometry('700x650');self.minsize(640,620)
        self.configure(bg=t.BG);self.transient(self.window)
        self.window.auto_children.add(self);self.protocol('WM_DELETE_WINDOW',self.close)
        body=tk.Frame(self,bg=t.BG);body.pack(fill='both',expand=True,padx=18,pady=14)
        row=tk.Frame(body,bg=t.BG);row.pack(fill='x')
        self.saved=tk.StringVar();self.saved_combo=ttk.Combobox(row,textvariable=self.saved,state='readonly')
        self.saved_combo.pack(side='left',fill='x',expand=True)
        self.saved_combo.bind('<<ComboboxSelected>>',self.select_saved)
        t.button(row,'IMPORT MP3 / WAV',self.import_audio).pack(side='right',padx=(8,0))
        self.values={}
        for key,label in (('name','Track name'),('artist','Artist'),('source','Source / licence page')):
            t.label(body,label,9,t.MUTED).pack(anchor='w',pady=(7,0))
            var=tk.StringVar();self.values[key]=var;tk.Entry(body,textvariable=var).pack(fill='x')
        t.label(body,'Licence type — copy the information supplied with the download',9,t.MUTED).pack(anchor='w',pady=(7,0))
        self.licence=tk.StringVar()
        licence=ttk.Combobox(body,textvariable=self.licence,values=LICENCES,state='readonly');licence.pack(fill='x')
        self.required=tk.BooleanVar()
        licence.bind('<<ComboboxSelected>>',lambda _:self.required.set(self.licence.get()=='Creative Commons Attribution'))
        tk.Checkbutton(body,text='Attribution required',variable=self.required,bg=t.BG,fg=t.TEXT,selectcolor=t.CONTROL).pack(anchor='w')
        self.credit=tk.Text(body,height=4,wrap='word',bg=t.CONTROL,fg=t.TEXT,insertbackground=t.TEXT)
        self.credit.pack(fill='both',expand=True)
        t.label(body,'Paste the exact credit supplied by YouTube or the rights holder.',9,t.MUTED).pack(anchor='w')
        t.button(body,'COPY YOUTUBE DESCRIPTION CREDIT',self.copy_credit).pack(anchor='w',pady=6)
        trim=tk.Frame(body,bg=t.BG);trim.pack(fill='x',pady=5)
        music=self.window.edits.music
        self.start=tk.StringVar(value=f'{music.trim_start:g}')
        self.end=tk.StringVar(value='' if music.trim_end is None else f'{music.trim_end:g}')
        for label,var in (('Track start (s)',self.start),('Track end (blank = full)',self.end)):
            t.label(trim,label,9).pack(side='left',padx=4);tk.Entry(trim,textvariable=var,width=9).pack(side='left')
        self.duck=tk.BooleanVar(value=music.duck_dialogue)
        tk.Checkbutton(body,text='Duck music under source dialogue',variable=self.duck,bg=t.BG,fg=t.TEXT,selectcolor=t.CONTROL).pack(anchor='w')
        actions=tk.Frame(body,bg=t.BG);actions.pack(fill='x',pady=8)
        for label,action in (('PREVIEW 12s',self.preview),('STOP',self.stop),('APPLY MIX',self.apply),('SAVE TRACK',self.save)):
            t.button(actions,label,action).pack(side='left',padx=(0,6))
        self.note=t.label(body,'',9,t.MUTED,wraplength=640,justify='left');self.note.pack(fill='x')
        self.audition=Audition(self,lambda message,error:self.note.configure(text=message,fg=t.RED if error else t.CYAN))
        self.refresh_saved();self.load_current()

    def refresh_saved(self):
        self.records=self.library.items()
        self.saved_combo.configure(values=[f"{r['name']} — {r['artist'] or 'Unknown artist'} [{r['id'][:6]}]" for r in self.records])

    def load_current(self):
        music=self.window.edits.music
        record=self.library.find(music.imported) if music.track==IMPORT_LABEL and music.imported else None
        record=record or dict(name=Path(music.imported).stem if music.track==IMPORT_LABEL and music.imported else music.track,
            artist='' if music.track==IMPORT_LABEL else 'Pulse Capture',source='Local file' if music.track==IMPORT_LABEL else 'Pulse original composition',
            licence=LICENCES[0] if music.track==IMPORT_LABEL else 'Pulse Original Media',requires_attribution=False,attribution='')
        for key,var in self.values.items():var.set(record.get(key,''))
        self.licence.set(record['licence']);self.required.set(record['requires_attribution'])
        self.credit.delete('1.0','end');self.credit.insert('1.0',record['attribution'])

    def record(self):
        return dict(**{k:v.get().strip() for k,v in self.values.items()},licence=self.licence.get(),
                    requires_attribution=self.required.get(),attribution=self.credit.get('1.0','end-1c'))

    def state(self):
        music=replace(self.window.edits.music,enabled=True,trim_start=float(self.start.get()),
                      trim_end=float(self.end.get()) if self.end.get().strip() else None,duck_dialogue=self.duck.get())
        music.validate();return music

    def apply(self):
        if self.busy or self.window.exporter.busy or self.window.closing:return False
        try:
            music=self.state();self.window.edits=replace(self.window.edits,music=music)
            self.tools.sync();self.tools.changed()
            self.note.configure(text='Track trim and dialogue ducking applied. Volume, loop and fades remain in the Music panel.',fg=t.GREEN)
            return True
        except (ValueError,TypeError) as exc:self.note.configure(text=str(exc),fg=t.RED);return False

    def select_saved(self,_=None):
        if self.busy or self.window.exporter.busy:return
        index=self.saved_combo.current()
        if index<0:return
        self.stop();item=self.records[index]
        self.tools.imported=self.library.path(item);self.tools.track_choice.set(IMPORT_LABEL);self.tools.music_on.set(True)
        self.window.edits=replace(self.window.edits,music=replace(self.window.edits.music,trim_start=0,trim_end=None))
        self.tools.changed();self.tools.sync()
        self.start.set('0');self.end.set('');self.load_current()

    def import_audio(self):
        if self.busy or self.window.exporter.busy:return
        self.stop();self.tools.import_audio();self.start.set('0');self.end.set('');self.load_current()

    def copy_credit(self):
        try:
            credit=description_credit(self.record())
            if not credit:raise ValueError('This track is not marked as requiring attribution.')
            self.clipboard_clear();self.clipboard_append(credit)
            self.note.configure(text='Copied the supplied credit to the clipboard.',fg=t.GREEN)
        except ValueError as exc:self.note.configure(text=str(exc),fg=t.RED)

    def preview(self):
        if self.window.exporter.busy:return
        try:
            music=self.state()
            ffmpeg=self.window.backend.ffmpeg
            def command(destination):
                path=resolve_music_path(music)
                args=[str(ffmpeg),'-v','error','-nostdin','-n']
                if input_loops(music):args+=['-stream_loop','-1']
                return args+['-i',str(path),'-af',','.join(filters(music,12)), '-t','12','-ac','2','-ar','48000','-c:a','pcm_s16le',str(destination)]
            self.audition.play(command)
        except (ValueError,TypeError) as exc:self.note.configure(text=str(exc),fg=t.RED)

    def stop(self):self.audition.stop()

    def save(self):
        if self.busy or self.window.exporter.busy or self.window.closing:return
        if self.window.edits.music.track!=IMPORT_LABEL:
            self.note.configure(text='Pulse original tracks are already included. Import a downloaded MP3 or WAV to save its licence record.',fg=t.MUTED);return
        from .music_library import validate_record
        try:
            record=self.record();validate_record(record)
            music=self.state();path=music.imported;expected=self.window.edits.music
        except (ValueError,TypeError) as exc:self.note.configure(text=str(exc),fg=t.RED);return
        self.busy=True;self.note.configure(text='Validating and saving an owned library copy…',fg=t.CYAN)
        def work():
            try:self.events.put((self.library.save(path,record,self.window.backend.ffprobe),None,music,expected))
            except Exception as exc:self.events.put((None,str(exc),music,expected))
        threading.Thread(target=work,daemon=True).start();self.after(60,self.poll_save)

    def poll_save(self):
        try:item,error,music,expected=self.events.get_nowait()
        except Empty:self.after(60,self.poll_save);return
        self.busy=False
        if self.closed:self.finish_close();return
        if error:self.note.configure(text=error,fg=t.RED);return
        # An asynchronous save never overwrites a newer music selection or export.
        if not self.window.exporter.busy and self.window.edits.music==expected:
            self.window.edits=replace(self.window.edits,music=replace(music,imported=self.library.path(item)))
            self.tools.sync();self.tools.changed()
        self.refresh_saved();self.note.configure(text='Saved track and licence record. The downloaded source is unchanged.',fg=t.GREEN)

    def close(self):
        if self.closed:return
        self.closed=True;self.audition.close()
        if self.busy:self.withdraw()
        else:self.finish_close()

    def finish_close(self):
        self.window.auto_children.discard(self);self.destroy()
