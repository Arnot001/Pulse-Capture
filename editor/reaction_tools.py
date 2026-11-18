"""Compact library/cue editor, using the existing Quick Edit preview and export."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from queue import Queue, Empty
import subprocess
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, ttk, simpledialog

from capture.ffmpeg_backend import process_options
from ui import theme as t
from .reaction_library import ReactionLibrary, REACTION_CATEGORIES
from .media_audition import Audition
from .soundboard import matches, in_category, rights_label
from .reactions import SoundCue, VisualCue, POSITIONS, ANIMATIONS, validate_cues


class ReactionDialog(tk.Toplevel):
    def __init__(self, window, kind):
        super().__init__(window)
        self.window, self.kind = window, kind
        self.library = ReactionLibrary()
        self.title({'sfx':'REACTION AUDIO / SOUND FX','emoji':'EMOJIS','gif':'GIFS / REACTIONS'}[kind])
        self.geometry('840x690'); self.minsize(760,620)
        self.configure(bg=t.BG); self.transient(window)
        self.closed = False; self.busy = False
        self.images = {}; self.preview_photo = None
        self.preview_timer = self.poll_timer = self.thumbnail_timer = None
        self.events = Queue(); self.temp = tempfile.TemporaryDirectory(prefix='pulse-audition-')
        self.import_cancel = threading.Event()
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
        if kind!='emoji':t.button(top,'IMPORT FILES',self.import_asset).pack(side='right')
        if kind=='sfx':
            browse=tk.Frame(self,bg=t.BG);browse.pack(fill='x',padx=16,pady=(0,5))
            self.audio_scope=tk.StringVar(value='All audio')
            scope=ttk.Combobox(browse,textvariable=self.audio_scope,values=('All audio','My recordings','Synthesized SFX','Windows voices'),state='readonly',width=18)
            scope.pack(side='left');scope.bind('<<ComboboxSelected>>',lambda _:self.refresh_library())
            t.button(browse,'FIND MEME SOUNDS',self.find_sounds).pack(side='left',padx=8)
            t.button(browse,'SUGGEST REACTION',self.suggest_reaction).pack(side='left')
            t.button(browse,'CREATE VOICE (OPTIONAL)',self.create_voice).pack(side='right')
        centre=tk.Frame(self,bg=t.BG);centre.pack(fill='both',expand=True,padx=16)
        style=ttk.Style(self);style.configure('Reactions.Treeview',rowheight=48)
        self.assets=ttk.Treeview(centre,show='tree',style='Reactions.Treeview',height=4,selectmode='extended')
        self.assets.pack(side='left',fill='both',expand=True)
        scrollbar=ttk.Scrollbar(centre,orient='vertical',command=self.assets.yview)
        scrollbar.pack(side='left',fill='y')
        self.assets.configure(yscrollcommand=lambda a,b:(scrollbar.set(a,b),self.queue_thumbnails()))
        self.assets.bind('<<TreeviewSelect>>',lambda _:self.preview_asset())
        preview=tk.Frame(centre,bg=t.PANEL,width=190);preview.pack(side='right',fill='y',padx=(10,0));preview.pack_propagate(False)
        self.picture=tk.Label(preview,bg=t.PANEL,fg=t.TEXT,text='Select an effect');self.picture.pack(fill='both',expand=True)
        t.button(preview,'▶ PREVIEW',self.preview_asset).pack(fill='x')
        t.button(preview,'STOP',self.stop_preview).pack(fill='x')
        t.button(preview,'★ FAVOURITE',self.favourite).pack(fill='x')
        t.button(preview,'SET CATEGORY',self.categorize).pack(fill='x')
        t.button(preview,'DETAILS / LICENCE',self.details).pack(fill='x')
        self.asset_label=t.label(self,'',9,t.MUTED,anchor='w',wraplength=720);self.asset_label.pack(fill='x',padx=16,pady=4)
        grid=tk.Frame(self,bg=t.BG);grid.pack(fill='x',padx=16)
        now=window.cuts.source_elapsed(window.position,window.trim)/window.edits.speed
        self.values={}
        fields=[('at' if kind=='sfx' else 'start','At / start',f'{now:.3f}'),
                ('duration' if kind=='sfx' else 'end','Duration (blank = full)' if kind=='sfx' else 'End', '' if kind=='sfx' else f'{min(self.total(),now+1.8):.3f}')]
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
        self.zone=tk.StringVar(value='bottom' if window.edits.comedy_bands else 'canvas')
        self.position=tk.StringVar(value='bottom_right');self.animation=tk.StringVar(value='pop');self.loop=tk.BooleanVar(value=True)
        options=tk.Frame(self,bg=t.BG);options.pack(fill='x',padx=16,pady=4)
        if kind!='sfx':
            zone_row=tk.Frame(self,bg=t.BG);zone_row.pack(fill='x',padx=16,pady=2)
            t.label(zone_row,'Layout zone',9).pack(side='left')
            ttk.Combobox(zone_row,textvariable=self.zone,values=('canvas','top','bottom'),state='readonly',width=12).pack(side='left',padx=8)
            t.label(zone_row,'Top / bottom stay inside Comedy Layout bands, including during animation.',9,t.MUTED).pack(side='left')
            for label,var,values in (('Position',self.position,POSITIONS),('Animation',self.animation,ANIMATIONS)):
                t.label(options,label,9).pack(side='left',padx=4)
                ttk.Combobox(options,textvariable=var,values=values,state='readonly',width=15).pack(side='left')
            tk.Checkbutton(options,text='Loop GIF',variable=self.loop,bg=t.BG,fg=t.TEXT,selectcolor=t.CONTROL).pack(side='left',padx=6)
            t.button(options,'POSITION ON VIDEO',self.position_on_video).pack(side='right')
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
        self.suggestion_note=''
        self.audition=Audition(self,lambda message,error:self.note.configure(
            text=message+ ('\n'+self.suggestion_note if self.suggestion_note else ''),fg=t.RED if error else t.CYAN))
        self.refresh_library();self.refresh_cues()

    def total(self):
        return self.window.edits.output_duration(self.window.cuts.kept_duration(self.window.trim))

    def selected(self):
        selected=self.assets.selection()
        if not selected:raise ValueError('Select a library asset first.')
        if len(selected)!=1:raise ValueError('Select one asset to insert. Multiple selection is for categories and favourites.')
        return selected[0]

    def refresh_library(self):
        if not hasattr(self,'assets'):return
        for item in self.assets.get_children():self.assets.delete(item)
        self.images.clear()
        prefs=self.library.preferences()
        values=self.library.items(self.kind)
        self.categories.configure(values=['All','Favourites','Recent',*sorted({x['category'] for x in values} | (set(REACTION_CATEGORIES) if self.kind=='sfx' else set()))])
        if self.kind=='sfx':
            from .reaction_suggestions import is_voice
            scope=self.audio_scope.get()
            values=[v for v in values if scope=='All audio' or
                    (scope=='My recordings' and v['id'].startswith('import.') and not is_voice(v)) or
                    (scope=='Synthesized SFX' and not v['id'].startswith('import.')) or
                    (scope=='Windows voices' and is_voice(v))]
            values.sort(key=lambda v:2 if is_voice(v) else 0 if v['id'].startswith('import.') else 1)
        if self.category.get()=='Recent':
            values.sort(key=lambda x:prefs.get('recent',[]).index(x['id']) if x['id'] in prefs.get('recent',[]) else 999)
        for item in values:
            key=item['id'];cat=self.category.get()
            if not matches(item,self.search.get()):continue
            if cat=='Favourites' and key not in prefs.get('favourites',[]):continue
            if cat=='Recent' and key not in prefs.get('recent',[]):continue
            if cat not in ('All','Favourites','Recent') and not in_category(item,cat):continue
            star='★ ' if key in prefs.get('favourites',[]) else ''
            self.assets.insert('','end',iid=key,text=f'{star}{item["name"]}  ·  {item["category"]}')
        if self.kind=='sfx' and not self.assets.get_children():
            self.asset_label.configure(text='No matching local sound. FIND MEME SOUNDS searches open audio inside Pulse Capture.')
        self.queue_thumbnails()

    def queue_thumbnails(self):
        if self.kind!='sfx' and not self.closed and self.thumbnail_timer is None:
            self.thumbnail_timer=self.after(20,self.load_thumbnails)

    def load_thumbnails(self):
        self.thumbnail_timer=None
        if self.closed:return
        count=0
        for key in self.assets.get_children():
            if key in self.images or not self.assets.bbox(key):continue
            try:
                photo=tk.PhotoImage(master=self,file=str(self.library.thumbnail(key)))
                photo=photo.subsample(max(1,(max(photo.width(),photo.height())+39)//40))
                self.images[key]=photo;self.assets.item(key,image=photo)
            except (tk.TclError,ValueError):pass
            count+=1
            if count==4:self.queue_thumbnails();break

    def stop_preview(self):
        if self.preview_timer:self.after_cancel(self.preview_timer);self.preview_timer=None
        if hasattr(self,'audition'):self.audition.stop()

    def details(self):
        try:
            from .reaction_details import ReactionDetails
            ReactionDetails(self,self.selected())
        except ValueError as exc:self.note.configure(text=str(exc),fg=t.RED)

    def find_sounds(self):
        """Open the native discovery window; don't send searches to a browser."""
        if self.kind!='sfx' or self.closed:return
        try:
            from .meme_finder import MemeFinder
            MemeFinder(self)
        except (ValueError,OSError,tk.TclError) as exc:
            self.note.configure(text=str(exc),fg=t.RED)

    def suggest_reaction(self):
        try:
            from .reaction_suggestions import caption_context, suggest
            w=self.window
            if w.exporter.busy or w.closing:raise ValueError('Wait for export to finish.')
            captions,speech,total=caption_context(w)
            suggestions=suggest(self.library,captions,speech,total,w.edits.sounds,
                                getattr(self,'reviewed_suggestions',()))
            if not suggestions:
                raise ValueError('No suitable local reaction with a safe dialogue gap. Add descriptive captions and matching recorded clips; unknown speech stays protected. No voice was substituted.')
            cue,caption=suggestions[0]
            self.suggested_asset=cue.asset_id
            self.reviewed_suggestions=getattr(self,'reviewed_suggestions',set())|{cue.asset_id}
            self.audio_scope.set('My recordings');self.search.set('');self.category.set('All');self.refresh_library()
            self.fill_values(cue)
            w.seek(w.cuts.source_from_elapsed(cue.at*w.edits.speed,w.trim))
            self.suggestion_note=f'Suggested for “{caption[:90]}” at {cue.at:.2f}s. Preview the clip, then INSERT AT PLAYHEAD to accept. Nothing added yet.'
            self.note.configure(text=self.suggestion_note,fg=t.CYAN)
        except (ValueError,OSError) as exc:self.note.configure(text=str(exc),fg=t.RED)

    def categorize(self):
        selected=self.assets.selection()
        if not selected:return
        category=simpledialog.askstring('Category',f'Category for {len(selected)} selected assets (e.g. WTF, Disbelief, Rage, Cringe, Laughing, Dramatic):',parent=self)
        if category is None:return
        try:
            self.library.categorize(selected,category)
            self.category.set('All');self.refresh_library()
            self.assets.selection_set(selected)
        except (ValueError,OSError) as exc:self.note.configure(text=str(exc),fg=t.RED)

    def preview_asset(self):
        self.stop_preview()
        try:
            if len(self.assets.selection())!=1:return
            key=self.selected()
            if key!=getattr(self,'suggested_asset',None):self.suggestion_note=''
            item=self.library.metadata(key)
            rights=rights_label(item)
            self.asset_label.configure(text=f'{item["name"]} · {rights}' +
                (' — check permission before publishing.' if rights=='Unverified' else ''))
            if self.kind=='sfx':
                volume=float(self.values['volume'].get())
                from .reactions import finite
                finite(volume,0,2,'Preview volume')
                ffmpeg,library=self.window.backend.ffmpeg,self.library
                self.audition.play(lambda destination:[str(ffmpeg),'-v','error','-nostdin','-n',
                    '-i',str(library.resolve(key,'sfx')),'-af',f'volume={volume:g},alimiter=limit=.9:level=false:latency=true',
                    '-ac','2','-ar','48000','-c:a','pcm_s16le',str(destination)])
                self.picture.configure(text=self.library.metadata(key)['name'])
            else:
                self.animate(self.library.resolve(key,self.kind),0)
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
        try:
            for key in self.assets.selection():self.library.remember(key,True)
            self.refresh_library()
        except ValueError as exc:self.note.configure(text=str(exc),fg=t.RED)

    def import_asset(self):
        if self.busy:return
        chosen=filedialog.askopenfilenames(parent=self,title='Import your licensed local media (multiple files)',filetypes=[('Audio','*.wav *.mp3')] if self.kind=='sfx' else [('GIF','*.gif')])
        if not chosen:return
        self.import_cancel.clear()
        self.busy=True;self.note.configure(text='Validating and importing files…',fg=t.CYAN)
        def run():
            try:self.events.put((True,self.library.import_many(chosen,self.kind,self.window.backend.ffmpeg,self.window.backend.ffprobe,
                                                lambda i,n:self.events.put(('progress',(i,n))), self.import_cancel)))
            except Exception as exc:self.events.put((False,str(exc)))
        threading.Thread(target=run,daemon=True).start()
        self.poll_import()

    def create_voice(self):
        """Make an original spoken reaction, then import it as an ordinary sound cue."""
        if self.kind != 'sfx' or self.busy:return
        spoken=simpledialog.askstring('CREATE VOICE','Enter a short spoken reaction (up to 140 characters):',parent=self)
        if spoken is None:return
        try:
            from .voice_tools import validate_voice_text
            spoken=validate_voice_text(spoken)
        except ValueError as exc:
            self.note.configure(text=str(exc),fg=t.RED)
            return
        self.import_cancel.clear()
        self.busy=True;self.note.configure(text='Creating local Windows voice…',fg=t.CYAN)
        def run():
            try:
                from .voice_tools import generate_voice_import
                key=generate_voice_import(spoken,self.library,self.window.backend.ffmpeg,
                                          self.window.backend.ffprobe,self.import_cancel)
                self.events.put((True,dict(added=[key],duplicates=[],errors=[])))
            except Exception as exc:self.events.put((False,str(exc)))
        threading.Thread(target=run,daemon=True).start()
        self.poll_import()

    def poll_import(self):
        try:
            ok,result=self.events.get_nowait()
            if ok=='progress':
                if not self.closed:self.note.configure(text=f'Importing {result[0]} / {result[1]}…',fg=t.CYAN)
                self.poll_timer=self.after(60,self.poll_import);return
            self.busy=False
            if self.closed:self.finish_close();return
            self.note.configure(text=(f"Added {len(result['added'])} · duplicates {len(result['duplicates'])} · failed {len(result['errors'])}"
                + ('\n'+'\n'.join(result['errors'][:2]) if result['errors'] else '')) if ok else result,fg=t.GREEN if ok else t.RED)
            if ok:
                if self.kind=='sfx':self.audio_scope.set('All audio')
                self.search.set('');self.category.set('All');self.refresh_library()
                selected=tuple(dict.fromkeys(result['added']+result['duplicates']))
                self.assets.selection_set(selected)
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
        index=self.indices[self.cues.curselection()[0]]
        cue=self.tracks()[index]
        self.fill_values(cue)
        if self.kind!='sfx':
            self.window.video.select_visual(index)
            now=self.window.cuts.source_elapsed(self.window.position,self.window.trim)/self.window.edits.speed
            end=cue.end
            if cue.kind=='gif' and not cue.loop:
                end=min(end,cue.start+self.library.metadata(cue.asset_id,cue.kind)['duration'])
            if cue.start<=now<end:return
            # Show an entered animation rather than its transparent first frame.
            start=cue.start+min(.2,(end-cue.start)/2)
        else:start=cue.at
        self.window.seek(self.window.cuts.source_from_elapsed(start*self.window.edits.speed,self.window.trim))

    def fill_values(self,cue):
        for key,var in self.values.items():
            value=getattr(cue,key)
            var.set('' if value is None else format(value,'.9g'))
        if self.kind!='sfx':self.position.set(cue.position);self.animation.set(cue.animation);self.loop.set(cue.loop);self.zone.set(cue.zone)
        if self.assets.exists(cue.asset_id) and self.assets.selection()!=(cue.asset_id,):
            self.assets.selection_set(cue.asset_id)

    def sync_from_canvas(self,index,cue):
        if self.kind=='sfx':return
        if cue.kind!=self.kind:
            self.cues.selection_clear(0,'end')
            return
        expected=[i for i,c in enumerate(self.tracks()) if c.kind==self.kind]
        if self.indices!=expected:self.refresh_cues()
        row=self.indices.index(index)
        if self.cues.curselection()!=(row,):
            self.cues.selection_clear(0,'end');self.cues.selection_set(row);self.cues.see(row)
        self.fill_values(cue)

    def position_on_video(self):
        if not self.cues.curselection():
            self.note.configure(text='Insert or select a timed overlay first.',fg=t.RED)
            return
        self.select_cue()
        self.stop_preview()
        self.window.select_tool('FORMAT')
        self.withdraw()
        self.window.lift()
        self.window.note.configure(text='Drag the overlay; corners resize, round handle rotates. Reopen EMOJIS / GIFS for numeric controls.',fg=t.CYAN)

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
            cue=SoundCue(key,**values) if self.kind=='sfx' else VisualCue(self.kind,key,**values,position=self.position.get(),animation=self.animation.get(),loop=self.loop.get(),zone=self.zone.get())
            tracks=self.tracks()
            if update:
                if not self.cues.curselection():raise ValueError('Select a timed cue to update or replace.')
                index=self.indices[self.cues.curselection()[0]]
                tracks[index]=cue
            else:
                index=len(tracks);tracks.append(cue)
            self.commit(tracks)
            self.suggestion_note=''
            if self.kind!='sfx':self.window.video.select_visual(index)
            if key!='silence.pause':self.library.remember(key)
            self.note.configure(text='Cue saved. Preview placement in Quick Edit; export creates a new MP4.',fg=t.GREEN)
        except (ValueError,TypeError) as exc:self.note.configure(text=str(exc),fg=t.RED)

    def remove(self):
        try:
            if self.cues.curselection():
                values=self.tracks();del values[self.indices[self.cues.curselection()[0]]];self.commit(values)
                if self.kind!='sfx':self.window.video.select_visual(None)
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
            proposed=replace(w.edits,sounds=sounds,overlays=overlays)
            proposed.validate(w.media)
            w.stop_play();w.edits=proposed;w.update_timeline();w.request_frame();self.refresh_cues()
        except Exception as exc:self.note.configure(text=str(exc),fg=t.RED)

    def close(self):
        self.closed=True
        self.import_cancel.set()
        self.stop_preview();self.audition.close()
        if self.thumbnail_timer:self.after_cancel(self.thumbnail_timer);self.thumbnail_timer=None
        try:
            import winsound
            winsound.PlaySound(None,0)
        except (ImportError,RuntimeError):pass
        if self.busy:self.withdraw()
        else:self.finish_close()

    def finish_close(self):
        self.temp.cleanup();self.window.auto_children.discard(self);self.destroy()
