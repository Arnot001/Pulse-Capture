"""Compact library/cue editor, using the existing Quick Edit preview and export."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from queue import Queue, Empty
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from capture.ffmpeg_backend import process_options
from ui import theme as t
from .reaction_library import ReactionLibrary
from .reactions import SoundCue, VisualCue, POSITIONS, ANIMATIONS, validate_cues


class ReactionDialog(tk.Toplevel):
    def __init__(self, window, kind):
        super().__init__(window)
        self.window, self.kind = window, kind
        self.library = ReactionLibrary()
        self.title({'sfx':'SOUND FX','emoji':'EMOJIS','gif':'GIFS / REACTIONS'}[kind])
        self.geometry('840x690'); self.minsize(760,620)
        self.configure(bg=t.BG); self.transient(window)
        self.closed = False; self.busy = False
        self.images = {}; self.preview_photo = None
        self.preview_timer = self.poll_timer = None
        self.events = Queue(); self.temp = tempfile.TemporaryDirectory(prefix='pulse-audition-')
        self.protocol('WM_DELETE_WINDOW',self.close)
        window.auto_children.add(self)
        self.search = tk.StringVar(); self.category = tk.StringVar(value='All')
        top=tk.Frame(self,bg=t.BG);top.pack(fill='x',padx=16,pady=10)
        t.label(top,'Search',10).pack(side='left')
        tk.Entry(top,textvariable=self.search,width=22).pack(side='left',padx=6)
        categories=sorted({x['category'] for x in self.library.items(kind)})
        self.categories=ttk.Combobox(top,textvariable=self.category,values=['All','Favourites','Recent',*categories],width=16,state='readonly')
        self.categories.pack(side='left',padx=6)
        self.search.trace_add('write',lambda *_:self.refresh_library())
        self.category.trace_add('write',lambda *_:self.refresh_library())
        if kind!='emoji':t.button(top,'IMPORT LOCAL',self.import_asset).pack(side='right')
        centre=tk.Frame(self,bg=t.BG);centre.pack(fill='both',expand=True,padx=16)
        style=ttk.Style(self);style.configure('Reactions.Treeview',rowheight=48)
        self.assets=ttk.Treeview(centre,show='tree',style='Reactions.Treeview',height=4,selectmode='browse')
        self.assets.pack(side='left',fill='both',expand=True)
        self.assets.bind('<<TreeviewSelect>>',lambda _:self.preview_asset())
        preview=tk.Frame(centre,bg=t.PANEL,width=190);preview.pack(side='right',fill='y',padx=(10,0));preview.pack_propagate(False)
        self.picture=tk.Label(preview,bg=t.PANEL,fg=t.TEXT,text='Select an effect');self.picture.pack(fill='both',expand=True)
        t.button(preview,'▶ PREVIEW',self.preview_asset).pack(fill='x')
        t.button(preview,'★ FAVOURITE',self.favourite).pack(fill='x')
        self.asset_label=t.label(self,'',9,t.MUTED,anchor='w');self.asset_label.pack(fill='x',padx=16,pady=4)
        grid=tk.Frame(self,bg=t.BG);grid.pack(fill='x',padx=16)
        now=window.cuts.source_elapsed(window.position,window.trim)/window.edits.speed
        self.values={}
        fields=[('at' if kind=='sfx' else 'start','At / start',f'{now:.3f}'),
                ('duration' if kind=='sfx' else 'end','Duration' if kind=='sfx' else 'End', '1.8' if kind=='sfx' else f'{min(self.total(),now+1.8):.3f}')]
        if kind=='sfx':
            fields += [('volume','Volume 0–2','.75'),('duck_source','Background gain','1'),('fade_in','Fade in','.005'),('fade_out','Fade out','.03')]
        else:
            fields += [('scale','Size .05–.6','.2'),('opacity','Opacity 0–1','1'),('rotation','Rotation','0'),('x','X 0–1 (optional)',''),('y','Y 0–1 (optional)','')]
        for i,(key,label,value) in enumerate(fields):
            group=tk.Frame(grid,bg=t.BG);group.grid(row=i//4,column=i%4,sticky='ew',padx=(0,10),pady=3)
            grid.columnconfigure(i%4,weight=1)
            t.label(group,label,9).pack(anchor='w')
            var=tk.StringVar(value=value);self.values[key]=var
            tk.Entry(group,textvariable=var,width=15).pack(fill='x')
        self.position=tk.StringVar(value='bottom_right');self.animation=tk.StringVar(value='pop');self.loop=tk.BooleanVar(value=True)
        options=tk.Frame(self,bg=t.BG);options.pack(fill='x',padx=16,pady=4)
        if kind!='sfx':
            for label,var,values in (('Position',self.position,POSITIONS),('Animation',self.animation,ANIMATIONS)):
                t.label(options,label,9).pack(side='left',padx=4)
                ttk.Combobox(options,textvariable=var,values=values,state='readonly',width=15).pack(side='left')
            tk.Checkbutton(options,text='Loop GIF',variable=self.loop,bg=t.BG,fg=t.TEXT,selectcolor=t.CONTROL).pack(side='left',padx=6)
        else:
            t.button(options,'ADD SILENCE',lambda:self.save(False,'silence.pause')).pack(side='left')
            t.label(options,'Background gain: 1 = unchanged, 0 = mute source + music',9,t.MUTED).pack(side='left',padx=8)
        row=tk.Frame(self,bg=t.BG);row.pack(fill='x',padx=16,pady=5)
        for label,command in (('INSERT AT PLAYHEAD',self.insert),('UPDATE / REPLACE',lambda:self.save(True)),('REMOVE CUE',self.remove),('SAVE CUES',self.save_cues),('LOAD CUES',self.load_cues)):
            button=t.button(row,label,command);button.configure(font=(t.FONT,-9,'bold'),padx=7,pady=5);button.pack(side='left',padx=(0,5))
        self.cues=tk.Listbox(self,height=5,bg=t.CONTROL,fg=t.TEXT,exportselection=False)
        self.cues.pack(fill='x',padx=16,pady=5);self.cues.bind('<<ListboxSelect>>',self.select_cue)
        self.note=t.label(self,'All cue times refer to the output after trims, cuts and speed. Use only media you own or may use.',9,t.MUTED,wraplength=790,justify='left')
        self.note.pack(fill='x',padx=16,pady=8)
        self.refresh_library();self.refresh_cues()

    def total(self):
        return self.window.edits.output_duration(self.window.cuts.kept_duration(self.window.trim))

    def selected(self):
        selected=self.assets.selection()
        if not selected:raise ValueError('Select a library asset first.')
        return selected[0]

    def refresh_library(self):
        if not hasattr(self,'assets'):return
        for item in self.assets.get_children():self.assets.delete(item)
        self.images.clear()
        prefs=self.library.preferences()
        values=self.library.items(self.kind)
        if self.category.get()=='Recent':
            values.sort(key=lambda x:prefs.get('recent',[]).index(x['id']) if x['id'] in prefs.get('recent',[]) else 999)
        for item in values:
            key=item['id'];cat=self.category.get()
            if self.search.get().lower() not in (item['name']+' '+key).lower():continue
            if cat=='Favourites' and key not in prefs.get('favourites',[]):continue
            if cat=='Recent' and key not in prefs.get('recent',[]):continue
            if cat not in ('All','Favourites','Recent',item['category']):continue
            image=''
            if self.kind!='sfx':
                try:
                    photo=tk.PhotoImage(master=self,file=str(self.library.resolve(key)))
                    photo=photo.subsample(max(1,(max(photo.width(),photo.height())+39)//40))
                    self.images[key]=photo;image=photo
                except (tk.TclError,ValueError):pass
            star='★ ' if key in prefs.get('favourites',[]) else ''
            self.assets.insert('','end',iid=key,text=f'{star}{item["name"]}  ·  {item["category"]}',image=image)

    def preview_asset(self):
        if self.preview_timer:self.after_cancel(self.preview_timer);self.preview_timer=None
        try:
            key=self.selected();path=self.library.resolve(key,self.kind)
            self.asset_label.configure(text=key)
            if self.kind=='sfx':
                import winsound
                winsound.PlaySound(None,0)
                destination=Path(self.temp.name)/'audition.wav'
                volume=float(self.values['volume'].get())
                from .reactions import finite
                finite(volume,0,2,'Preview volume')
                subprocess.run([str(self.window.backend.ffmpeg),'-v','error','-nostdin','-y','-i',str(path),
                                '-af',f'volume={volume:g},alimiter=limit=.9:level=false:latency=true',str(destination)],
                               check=True,capture_output=True,timeout=25,**process_options())
                winsound.PlaySound(str(destination),winsound.SND_FILENAME|winsound.SND_ASYNC)
                self.picture.configure(text=self.library.metadata(key)['name'])
            else:
                self.animate(path,0)
        except Exception as exc:self.note.configure(text=str(exc),fg=t.RED)

    def animate(self,path,index):
        if self.closed:return
        try:
            photo=tk.PhotoImage(master=self,file=str(path),format=f'gif -index {index}' if self.kind=='gif' else 'png')
        except tk.TclError:
            if index:self.animate(path,0)
            return
        self.preview_photo=photo.subsample(max(1,(max(photo.width(),photo.height())+169)//170))
        self.picture.configure(image=self.preview_photo,text='')
        if self.kind=='gif':
            delays = self.library.metadata(path.stem).get('delays', [])
            delay = delays[index] if index < len(delays) else .1
            self.preview_timer=self.after(round(delay*1000),lambda:self.animate(path,index+1))

    def favourite(self):
        try:self.library.remember(self.selected(),True);self.refresh_library()
        except ValueError as exc:self.note.configure(text=str(exc),fg=t.RED)

    def import_asset(self):
        if self.busy:return
        chosen=filedialog.askopenfilename(parent=self,title='Import your licensed local media',filetypes=[('Audio','*.wav *.mp3')] if self.kind=='sfx' else [('GIF','*.gif')])
        if not chosen:return
        self.busy=True;self.note.configure(text='Validating and copying this asset…',fg=t.CYAN)
        def run():
            try:self.events.put((True,self.library.import_file(chosen,self.kind,self.window.backend.ffmpeg,self.window.backend.ffprobe)))
            except Exception as exc:self.events.put((False,str(exc)))
        threading.Thread(target=run,daemon=True).start()
        self.poll_import()

    def poll_import(self):
        try:
            ok,result=self.events.get_nowait();self.busy=False
            if self.closed:self.finish_close();return
            self.note.configure(text=f'Imported: {result}' if ok else result,fg=t.GREEN if ok else t.RED)
            if ok:
                self.category.set('All');self.refresh_library();self.assets.selection_set(result)
        except Empty:self.poll_timer=self.after(80,self.poll_import)

    def tracks(self):return list(self.window.edits.sounds if self.kind=='sfx' else self.window.edits.overlays)

    def refresh_cues(self):
        self.cues.delete(0,'end')
        self.indices=[]
        for i,cue in enumerate(self.tracks()):
            if self.kind!='sfx' and cue.kind!=self.kind:continue
            self.indices.append(i)
            start=cue.at if self.kind=='sfx' else cue.start
            end=start+cue.length() if self.kind=='sfx' else cue.end
            self.cues.insert('end',f'{start:.3f} – {end:.3f}s  {cue.asset_id}')

    def select_cue(self,_=None):
        if not self.cues.curselection():return
        cue=self.tracks()[self.indices[self.cues.curselection()[0]]]
        for key,var in self.values.items():
            value=getattr(cue,key)
            var.set('' if value is None else str(value))
        if self.kind!='sfx':self.position.set(cue.position);self.animation.set(cue.animation);self.loop.set(cue.loop)
        if self.assets.exists(cue.asset_id):self.assets.selection_set(cue.asset_id)
        start=cue.at if self.kind=='sfx' else cue.start
        self.window.seek(self.window.cuts.source_from_elapsed(start*self.window.edits.speed,self.window.trim))

    def commit(self,values):
        w=self.window
        if w.exporter.busy or w.closing:raise ValueError('Wait for export to finish before changing cues.')
        edits=replace(w.edits,**{'sounds' if self.kind=='sfx' else 'overlays':tuple(values)})
        validate_cues(edits.sounds,edits.overlays,self.total());edits.validate(w.media)
        w.stop_play();w.edits=edits;w.update_timeline();w.request_frame();self.refresh_cues()

    def insert(self):
        now=self.window.cuts.source_elapsed(self.window.position,self.window.trim)/self.window.edits.speed
        self.values['at' if self.kind=='sfx' else 'start'].set(f'{now:.3f}')
        if self.kind!='sfx':self.values['end'].set(f'{min(self.total(),now+1.8):.3f}')
        self.save(False)

    def save(self,update,asset_id=None):
        try:
            key=asset_id or self.selected()
            values={key:(None if not var.get().strip() else float(var.get())) for key,var in self.values.items()}
            cue=SoundCue(key,**values) if self.kind=='sfx' else VisualCue(self.kind,key,**values,position=self.position.get(),animation=self.animation.get(),loop=self.loop.get())
            tracks=self.tracks()
            if update:
                if not self.cues.curselection():raise ValueError('Select a timed cue to update or replace.')
                tracks[self.indices[self.cues.curselection()[0]]]=cue
            else:tracks.append(cue)
            self.commit(tracks)
            if key!='silence.pause':self.library.remember(key)
            self.note.configure(text='Cue saved. Preview placement in Quick Edit; export creates a new MP4.',fg=t.GREEN)
        except (ValueError,TypeError) as exc:self.note.configure(text=str(exc),fg=t.RED)

    def remove(self):
        try:
            if self.cues.curselection():
                values=self.tracks();del values[self.indices[self.cues.curselection()[0]]];self.commit(values)
        except ValueError as exc:self.note.configure(text=str(exc),fg=t.RED)

    def save_cues(self):
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.json',title='Save a new output cue file')
        if not path:return
        try:
            from .pulse_plan import source_identity
            w=self.window
            data=dict(format='pulse-cues',version=1,source=source_identity(w.media,threading.Event()),duration=self.total(),
                      trim=asdict(w.trim),cuts=[asdict(c) for c in w.cuts.ranges],speed=w.edits.speed,
                      sfx=[asdict(c) for c in w.edits.sounds],overlays=[asdict(c) for c in w.edits.overlays])
            with Path(path).open('x',encoding='utf-8') as stream:json.dump(data,stream,indent=2)
            self.note.configure(text='Saved cues with their source identity and output timing.',fg=t.GREEN)
        except Exception as exc:self.note.configure(text=str(exc),fg=t.RED)

    def load_cues(self):
        path=filedialog.askopenfilename(parent=self,filetypes=[('Pulse cues','*.json')])
        if not path:return
        try:
            from .pulse_plan import source_identity,reaction_cues,fields
            w=self.window
            with Path(path).open('rb') as stream:raw=stream.read(256001)
            if len(raw)>256000:raise ValueError('Cue file exceeds 256 KB.')
            data=json.loads(raw)
            fields(data,('format','version','source','duration','trim','cuts','speed','sfx','overlays'))
            if (data['format']!='pulse-cues' or data['version']!=1 or data['source']!=source_identity(w.media,threading.Event()) or
                data['trim']!=asdict(w.trim) or data['cuts']!=[asdict(c) for c in w.cuts.ranges] or data['speed']!=w.edits.speed):
                raise ValueError('Cue file belongs to a different source or trim/cut/speed selection.')
            sounds,overlays=reaction_cues(data);validate_cues(sounds,overlays,self.total())
            if w.exporter.busy:raise ValueError('Wait for export to finish.')
            w.stop_play();w.edits=replace(w.edits,sounds=sounds,overlays=overlays);w.update_timeline();w.request_frame();self.refresh_cues()
        except Exception as exc:self.note.configure(text=str(exc),fg=t.RED)

    def close(self):
        self.closed=True
        if self.preview_timer:self.after_cancel(self.preview_timer)
        try:
            import winsound
            winsound.PlaySound(None,0)
        except (ImportError,RuntimeError):pass
        if self.busy:self.withdraw()
        else:self.finish_close()

    def finish_close(self):
        self.temp.cleanup();self.window.auto_children.discard(self);self.destroy()
