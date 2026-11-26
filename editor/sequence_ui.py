"""Clip management inside the existing Quick Edit timeline."""
from dataclasses import replace
from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk
from uuid import uuid4
from ui import theme as t
from .edit_history import EditSnapshot, EditHistory
from .models import format_time, parse_time
from .sequence import SourceClip, positions, project_media, split_clip, remap_state, validate_sequence
from .timeline_edits import TimelineBlock, output_time


class SequenceControls:
    def __init__(self, window, parent):
        self.w=window
        self.base=None
        self.drag=None
        self.pending=None
        self.loading=False
        self.results=Queue()
        row=tk.Frame(parent,bg=t.BG)
        row.pack(fill='x',before=window.timeline)
        for title,action in (('+ ADD CLIP',self.add),('SPLIT',self.split),('DUPLICATE',self.duplicate),('TRIM CLIP',self.trim),('REMOVE',self.remove)):
            button=t.button(row,title,action)
            button.configure(padx=6,pady=3,font=(t.FONT,-9,'bold'))
            button.pack(side='left',padx=(0,3))
            window.controls.append(button)
        self.anchor=tk.StringVar(value='Follow clips')
        self.anchor_picker=ttk.Combobox(row,textvariable=self.anchor,values=('Follow clips','Project time'),state='readonly',width=13)
        self.anchor_picker.pack(side='right')
        self.anchor_picker.bind('<<ComboboxSelected>>',self.anchor_changed)
        self.info=t.label(parent,'Select a video block · drag to reorder · edges trim · wheel zooms',8,t.MUTED)
        self.info.pack(fill='x',before=window.timeline)
        self.scroll=ttk.Scrollbar(parent,orient='horizontal',command=self.scroll_to)
        self.scroll.pack(fill='x')
        window.timeline.on_select=self.describe
        window.workspace_actions.add_separator()
        window.workspace_actions.add_command(label='Save edit project…',command=self.save)
        window.workspace_actions.add_command(label='Open edit project…',command=self.load)
        self.drop=None
        window.after_idle(self.install_drop)

    def ready(self):
        return bool(self.w.media and not self.w.exporter.busy and not self.w.closing and not self.loading)

    def clips(self):
        if self.base is None: self.base=self.w.media
        return self.w.edits.sequence or (SourceClip('original',self.base,0,self.base.duration),)

    def selected(self):
        key=self.w.timeline.selected_key
        if key and key[0]=='source': return key[1]
        self.w.note.configure(text='Select a video clip on the VIDEO track first.',fg=t.CYAN)
        return None

    def describe(self):
        key=self.w.timeline.selected_key
        if key and key[0]=='source':
            seq=self.clips()
            if key[1]>=len(seq): return
            clip,a,b=list(positions(seq))[key[1]]
            self.info.configure(text=f'{clip.media.path.name} · {format_time(a)} → {format_time(b)} · duration {format_time(clip.duration)} · source {format_time(clip.start)} → {format_time(clip.end)}')

    def decorate(self):
        if not self.w.media:return
        seq=self.clips()
        existing=tuple(b for b in self.w.timeline.clip_blocks if b.kind!='video')
        blocks=[]
        for index,(clip,a,b) in enumerate(positions(seq)):
            left,right=output_time(a,self.w),output_time(b,self.w)
            if right>left: blocks.append(TimelineBlock('source',index,0,left,right,clip.media.path.name))
        self.w.timeline.clip_blocks=existing+tuple(blocks)
        timeline=self.w.timeline
        timeline.view_start=max(0,min(timeline.view_start,max(0,timeline.output_duration-timeline.visible_span())))
        total=max(.001,timeline.output_duration)
        self.scroll.set(timeline.view_start/total,min(1,(timeline.view_start+timeline.visible_span())/total))
        self.anchor.set('Follow clips' if self.w.edits.overlay_anchor=='clips' else 'Project time')
        self.describe()

    def scroll_to(self,*args):
        timeline=self.w.timeline
        if args[0]=='moveto': start=float(args[1])*timeline.output_duration
        else: start=timeline.view_start+int(args[1])*timeline.visible_span()*(.8 if args[2]=='pages' else .1)
        timeline.view_start=max(0,min(start,timeline.output_duration-timeline.visible_span()))
        self.decorate();timeline.draw()

    def anchor_changed(self,_=None):
        if not self.ready():return
        before=EditSnapshot(self.w.trim,self.w.cuts,self.w.edits)
        after=replace(before,edits=replace(before.edits,overlay_anchor='clips' if self.anchor.get()=='Follow clips' else 'project'))
        self.record(before,after)
        self.w.edits=after.edits
        self.w.note.configure(text='Timed overlays follow their source clips.' if self.anchor.get()=='Follow clips' else 'Timed overlays keep project timestamps; shortening the project clips them at its end.',fg=t.CYAN)

    def add(self,paths=None):
        if not self.ready():return
        paths=paths or filedialog.askopenfilenames(parent=self.w,title='Append video clips',filetypes=[('Videos','*.mp4 *.mov *.mkv *.webm *.avi *.m4v'),('All files','*.*')])
        if not paths:return
        if len(self.clips())+len(paths)>64:
            self.w.note.configure(text='Keep this project to 64 clips or fewer.',fg=t.RED);return
        self.loading=True
        self.w.note.configure(text=f'Checking {len(paths)} new clip(s)…',fg=t.CYAN)
        def probe():
            from .media import probe_media
            try: self.results.put((tuple(SourceClip.from_media(probe_media(self.w.backend.ffprobe,Path(path))) for path in paths),None))
            except Exception as exc:self.results.put((None,str(exc)))
        threading.Thread(target=probe,daemon=True,name='Pulse clip metadata').start()
        self.w.after(60,self.poll_import)

    def poll_import(self):
        if self.w.closed or self.w.closing:return
        try: clips,error=self.results.get_nowait()
        except Empty:self.w.after(60,self.poll_import);return
        self.loading=False
        if error:self.w.note.configure(text=error,fg=t.RED);return
        self.change(self.clips()+clips, message=f'Added {len(clips)} clip(s).')

    def record(self,before,after):
        w=self.w
        if w.timeline_history is None or w.timeline_history.current!=before:w.timeline_history=EditHistory(before)
        w.timeline_history.record(after)

    def restore_media(self):
        w=self.w
        if self.base is None:self.base=w.media
        media=project_media(w.edits.sequence,self.base) if w.edits.sequence else self.base
        if media==w.media:return
        # Close each existing owner before creating another worker/device session.
        for worker in (w.preview,w.playback,w.audio_player):
            if worker:worker.close()
        for worker in (w.preview,w.playback):
            if worker:worker._thread.join(timeout=2)
        from .preview import Preview
        from .playback_preview import PlaybackPreview
        from .audio_preview import AudioPlayback
        w.media=media;w.video.media=media
        w.preview=Preview(w.backend.ffmpeg,media)
        w.playback=PlaybackPreview(w.backend.ffmpeg,media)
        w.audio_player=AudioPlayback(w.backend.ffmpeg,media)
        w.path=media.path
        w.position=min(w.position,media.duration)
        w.token+=1

    def change(self,new,origins=None,message='Timeline updated.'):
        if not self.ready():return
        w=self.w
        try:
            validate_sequence(new,True)
            before=EditSnapshot(w.trim,w.cuts,w.edits)
            after=remap_state(before,self.clips(),new,origins)
            media=project_media(new,self.base)
            after.edits.validate(media);after.cuts.validate_selection(media,after.trim)
            w.stop_play()
            self.record(before,after)
            w.edits,w.trim,w.cuts=after.edits,after.trim,after.cuts
            self.restore_media()
            w.timeline.selected_key=None
            w.update_trim(w.trim)
            w.overlay_tools.refresh();w.request_frame()
            w.note.configure(text=message+' Ctrl+Z to undo. '+('Timed overlays followed the clips.' if w.edits.overlay_anchor=='clips' else 'Timed overlays kept project time.'),fg=t.CYAN)
        except (ValueError,OSError) as exc:w.note.configure(text=str(exc),fg=t.RED)

    def split(self):
        if not self.ready():return
        index=self.selected()
        if index is None:return
        try:
            new,origins=split_clip(self.clips(),index,self.w.position)
            self.change(new,origins,'Clip split at the playhead.')
        except ValueError as exc:self.w.note.configure(text=str(exc),fg=t.RED)

    def duplicate(self):
        if not self.ready():return
        index=self.selected()
        if index is None:return
        seq=self.clips();copy=replace(seq[index],id=uuid4().hex)
        self.change(seq[:index+1]+(copy,)+seq[index+1:],{copy.id:seq[index].id},'Clip duplicated.')

    def remove(self):
        if not self.ready():return
        index=self.selected()
        if index is None:return
        seq=self.clips()
        self.change(seq[:index]+seq[index+1:],message='Clip removed; its original file is untouched.')

    def trim(self):
        if not self.ready():return
        index=self.selected()
        if index is None:return
        seq=self.clips();clip=seq[index]
        answer=simpledialog.askstring('Trim selected clip','Source start and end, separated by a comma:',initialvalue=f'{clip.start:.3f}, {clip.end:.3f}',parent=self.w)
        if not answer:return
        try:
            a,b=(parse_time(v.strip()) for v in answer.split(','))
            changed=replace(clip,start=a,end=b);changed.validate()
            self.change(seq[:index]+(changed,)+seq[index+1:],message='Clip trimmed.')
        except ValueError as exc:self.w.note.configure(text=str(exc),fg=t.RED)

    def begin_drag(self,key):
        if self.ready():self.drag=(key,self.clips());self.pending=None;self.describe()

    def change_drag(self,key,start,end):
        if self.drag is None:return
        self.pending=(start,end)
        timeline=self.w.timeline
        timeline.delete('clip-ghost')
        timeline.create_rectangle(timeline.block_x(start),69,timeline.block_x(end),90,outline=t.CYAN,width=3,tags='clip-ghost')

    def end_drag(self):
        drag,pending=self.drag,self.pending
        self.drag=self.pending=None
        if not drag or not pending:return
        key,seq=drag;index=key[1]
        clip,a,b=list(positions(seq))[index]
        old_a,old_b=output_time(a,self.w),output_time(b,self.w)
        left,right=pending
        if abs((right-left)-(old_b-old_a))<1e-6:
            target=self.w.cuts.source_from_elapsed(left*self.w.edits.speed,self.w.trim)
            others=list(seq);item=others.pop(index)
            destination=min(len(others),sum(1 for _,x,y in positions(others) if target>(x+y)/2))
            others.insert(destination,item)
            self.change(tuple(others),message='Clips reordered.')
        else:
            start=clip.start+(left-old_a)*self.w.edits.speed
            end=clip.end+(right-old_b)*self.w.edits.speed
            self.change(seq[:index]+(replace(clip,start=start,end=end),)+seq[index+1:],message='Clip trimmed.')

    def save(self):
        if not self.ready():return
        path=filedialog.asksaveasfilename(parent=self.w,title='Save edit project',defaultextension='.pulse.json',filetypes=[('Pulse edit project','*.pulse.json')])
        if not path:return
        try:
            from .project_file import save_project
            save_project(path,self.w.media,EditSnapshot(self.w.trim,self.w.cuts,self.w.edits))
            self.w.note.configure(text=f'Project saved: {Path(path).name}',fg=t.GREEN)
        except (ValueError,OSError) as exc:self.w.note.configure(text=str(exc),fg=t.RED)

    def load(self):
        if not self.ready():return
        path=filedialog.askopenfilename(parent=self.w,title='Open edit project',filetypes=[('Pulse edit project','*.pulse.json'),('JSON','*.json')])
        if not path:return
        try:
            from .project_file import load_project
            media,state=load_project(path)
            self.w.stop_play()
            self.base=media
            self.w.edits,self.w.trim,self.w.cuts=state.edits,state.trim,state.cuts
            self.restore_media()
            self.w.timeline_history=EditHistory(state)
            self.w.format_choice.set(state.edits.preset)
            self.w.brand_on.set(state.edits.branding.enabled)
            self.w.brand_corner.set(state.edits.branding.position)
            self.w.brand_size.set(state.edits.branding.size)
            self.w.comedy_on.set(state.edits.comedy_bands is not None)
            self.w.update_trim(state.trim)
            self.w.overlay_tools.refresh();self.w.music_tools.sync();self.w.polish_tools.sync()
            self.w.seek(state.trim.start)
            self.w.note.configure(text='Project restored.',fg=t.GREEN)
        except (ValueError,OSError,TypeError) as exc:self.w.note.configure(text=str(exc),fg=t.RED)

    def install_drop(self):
        from .windows_drop import FileDrop
        try:self.drop=FileDrop(self.w.timeline,lambda files:self.add(files))
        except OSError:pass

    def close(self):
        if self.drop:self.drop.close()
