"""Immutable source clips and explicit source/project timing. Originals stay read-only."""
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4
import math
from .models import MediaInfo, TrimRange


@dataclass(frozen=True)
class SourceClip:
    id: str
    media: MediaInfo
    start: float
    end: float

    @classmethod
    def from_media(cls, media):
        return cls(uuid4().hex, media, 0.0, media.duration)

    @property
    def duration(self):
        return self.end-self.start

    def validate(self):
        if not isinstance(self.id,str) or not self.id: raise ValueError('Clip needs an identifier.')
        TrimRange(self.start,self.end).validate(self.media)


def validate_sequence(clips, check_files=False):
    if not isinstance(clips,tuple) or not 1 <= len(clips) <= 64:
        raise ValueError('A project needs between 1 and 64 source clips.')
    if len({c.id for c in clips}) != len(clips): raise ValueError('Duplicate clip identifier.')
    for clip in clips:
        if not isinstance(clip,SourceClip): raise ValueError('Invalid source clip.')
        clip.validate()
        if check_files and not clip.media.path.is_file():
            raise ValueError(f'Missing source video: {clip.media.path}')


def positions(clips):
    at=0.0
    for clip in clips:
        yield clip,at,at+clip.duration
        at+=clip.duration


def project_media(clips, canvas=None):
    validate_sequence(clips)
    first=canvas or clips[0].media
    return MediaInfo(clips[0].media.path,sum(c.duration for c in clips),first.width,first.height,
                     30.0,any(c.media.has_audio for c in clips))


def locate(clips, time):
    total=sum(c.duration for c in clips)
    if not math.isfinite(time) or not 0<=time<=total: raise ValueError('Seek outside project.')
    for clip,a,b in positions(clips):
        if time < b or clip is clips[-1]: return clip,clip.start+min(clip.duration,time-a)


def split_clip(clips, index, project_time):
    clip,a,b=list(positions(clips))[index]
    point=clip.start+project_time-a
    left=replace(clip,end=point)
    right=replace(clip,id=uuid4().hex,start=point)
    left.validate();right.validate()
    return clips[:index]+(left,right)+clips[index+1:], {right.id:clip.id}


def mapped_intervals(old,new,start,end,origins=None):
    """Yield (new start, new end, old start) for retained source intersections."""
    origins=origins or {}
    for old_clip,a,b in positions(old):
        lo,hi=max(start,a),min(end,b)
        if hi<=lo: continue
        source_a,source_b=old_clip.start+lo-a,old_clip.start+hi-a
        for clip,c,d in positions(new):
            if origins.get(clip.id,clip.id)!=old_clip.id: continue
            x,y=max(source_a,clip.start),min(source_b,clip.end)
            if y>x: yield c+x-clip.start,c+y-clip.start,a+x-old_clip.start


def remap_state(state, old, new, origins=None):
    """Clips own captions/privacy/keys; output cues follow kept source intervals.

    Music, narration, watermarks, canvas and global effects stay project-wide.
    In project mode timed cues keep absolute times and are clipped at the new end.
    Existing cuts and outer trim always follow source content; appended clips are kept.
    """
    from .cuts import CutPlan, CutRange
    validate_sequence(new)
    total=sum(c.duration for c in new)
    old_total=sum(c.duration for c in old)
    exclusions=[(r.start,r.end) for r in state.cuts.ranges]
    if state.trim.start>0: exclusions.append((0,state.trim.start))
    if state.trim.end<old_total: exclusions.append((state.trim.end,old_total))
    ranges=sorted((a,b) for x,y in exclusions for a,b,_ in mapped_intervals(old,new,x,y,origins))
    merged=[]
    for a,b in ranges:
        if merged and a<=merged[-1][1]+1e-8: merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else: merged.append((a,b))
    cuts=CutPlan(tuple(CutRange(a,b) for a,b in merged))
    trim=TrimRange(0,total)
    edits=replace(state.edits,sequence=new)
    output_total=cuts.kept_duration(trim)/edits.speed
    if output_total<=0: raise ValueError('Keep at least one visible clip.')
    attached=edits.overlay_anchor=='clips'

    def source_intervals(start,end):
        if attached: return list(mapped_intervals(old,new,start,end,origins))
        return [(start,min(end,total),start)] if start<total else []

    def source_cues(cues):
        return tuple(replace(c,start=a,end=b) for c in cues
                     for a,b,_ in source_intervals(c.start,c.end) if b>a)

    def output_intervals(start,end):
        if not attached:
            return [(start,min(end,output_total),0)] if start<output_total else []
        result=[]
        elapsed=0
        for part in state.cuts.kept_segments(state.trim):
            length=part.duration/edits.speed
            lo,hi=max(start,elapsed),min(end,elapsed+length)
            if hi>lo:
                pa=part.start+(lo-elapsed)*edits.speed
                pb=part.start+(hi-elapsed)*edits.speed
                for a,b,old_at in mapped_intervals(old,new,pa,pb,origins):
                    na=cuts.source_elapsed(a,trim)/edits.speed
                    nb=cuts.source_elapsed(b,trim)/edits.speed
                    if nb>na: result.append((na,nb,lo-start+(old_at-pa)/edits.speed))
            elapsed+=length
        return result

    def output_cues(cues):
        result=[]
        for cue in cues:
            for a,b,offset in output_intervals(cue.start,cue.end):
                changes=dict(start=a,end=b)
                if hasattr(cue,'source_in'): changes['source_in']=cue.source_in+offset
                result.append(replace(cue,**changes))
        return tuple(result)

    sounds=[]
    for cue in edits.sounds:
        length=cue.duration if cue.duration is not None else cue.length()
        for a,b,offset in output_intervals(cue.at,cue.at+length):
            # SoundCue has no source-in: keep the trigger and truncate its tail.
            if offset<1e-8: sounds.append(replace(cue,at=a,duration=b-a))
    keys=[]
    for key in edits.crop_motion.keyframes:
        mapped=source_intervals(key.time,key.time+1e-7)
        keys.extend(replace(key,time=a) for a,_,_ in mapped)
    edits=replace(edits,text=replace(edits.text,captions=source_cues(edits.text.captions)),
                  privacy=replace(edits.privacy,masks=source_cues(edits.privacy.masks)),
                  crop_motion=replace(edits.crop_motion,keyframes=tuple(sorted(keys,key=lambda k:k.time))),
                  overlays=output_cues(edits.overlays),media_clips=output_cues(edits.media_clips),
                  commentary_clips=output_cues(edits.commentary_clips),sounds=tuple(sounds))
    return replace(state,trim=trim,cuts=cuts,edits=edits)
