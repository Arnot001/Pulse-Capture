"""Output-time timeline operations on the existing immutable Quick Edit models."""
from dataclasses import dataclass, replace
import math

from .edit_history import EditSnapshot
from .pulse_plan import timeline_positions
from .reaction_library import ReactionLibrary


TRACKS=('VIDEO','CAPTIONS','EMOJIS / GIFS','SOUND EFFECTS','VOICE','MUSIC','MOTION')


@dataclass(frozen=True)
class TimelineBlock:
    kind: str
    index: int
    track: int
    start: float
    end: float
    label: str

    @property
    def key(self):return self.kind,self.index


def output_time(source, state):
    return state.cuts.source_elapsed(source,state.trim)/state.edits.speed


def source_time(output, state):
    return state.cuts.source_from_elapsed(output*state.edits.speed,state.trim)


def duration(state):
    return state.edits.output_duration(state.cuts.kept_duration(state.trim))


def blocks(state, plan=None, library=None):
    """All displayed times use the final output clock, including assembled plans."""
    values=[];edits=state.edits;total=duration(state)
    for index,cue in enumerate(edits.text.captions):
        a,b=output_time(cue.start,state),output_time(cue.end,state)
        if b>a:values.append(TimelineBlock('caption',index,1,a,b,cue.text.replace('\n',' / ')))
    for index,cue in enumerate(edits.overlays):
        values.append(TimelineBlock('overlay',index,2,cue.start,cue.end,cue.asset_id))
    library=library or ReactionLibrary()
    for index,cue in enumerate(edits.sounds):
        voice=getattr(cue,'track','sfx')=='voice'
        values.append(TimelineBlock('sound',index,4 if voice else 3,cue.at,min(total,cue.at+cue.length(library)),cue.asset_id))
    if edits.music.enabled:
        values.append(TimelineBlock('music',0,5,getattr(edits.music,'at',0),total,edits.music.track))
    for index,key in enumerate(edits.crop_motion.keyframes):
        at=output_time(key.time,state)
        values.append(TimelineBlock('crop_key',index,6,at,at,'Crop'))
    if edits.zoom.enabled:values.append(TimelineBlock('zoom',0,6,0,total,f'Zoom {edits.zoom.factor:g}×'))
    if plan:
        for index,(item,(a,b)) in enumerate(zip(plan['timeline'],timeline_positions(plan))):
            a,b=output_time(a,state),output_time(b,state)
            if b>a:
                detail=f'{item.get("speed",1):g}×' if item['kind']=='shot' else item['kind']
                values.append(TimelineBlock('scene',index,0,a,b,f'{index+1} · {detail}'))
    else:
        for index,segment in enumerate(state.cuts.kept_segments(state.trim)):
            values.append(TimelineBlock('video',index,0,output_time(segment.start,state),output_time(segment.end,state),f'Video · {edits.speed:g}×'))
    return values


def snap_time(value, fps, targets=(), tolerance=0):
    if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('Timeline time must be finite.')
    nearest=min(targets,key=lambda x:abs(x-value)) if targets else None
    if nearest is not None and abs(nearest-value)<=tolerance:value=nearest
    return max(0,round(value*fps)/fps)


def change_timing(state, key, start, end, media):
    total=duration(state)
    if not all(type(x) in (int,float) and math.isfinite(x) for x in (start,end)) or not 0<=start<end<=total+1e-8:
        raise ValueError('Keep the clip inside the output timeline.')
    kind,index=key;edits=state.edits
    if kind=='caption':
        cues=list(edits.text.captions);cue=cues[index]
        cues[index]=replace(cue,start=source_time(start,state),end=source_time(end,state))
        edits=replace(edits,text=replace(edits.text,captions=tuple(cues)))
    elif kind=='overlay':
        cues=list(edits.overlays);cues[index]=replace(cues[index],start=start,end=end)
        edits=replace(edits,overlays=tuple(cues))
    elif kind=='sound':
        cues=list(edits.sounds);cue=cues[index]
        cues[index]=replace(cue,at=start,duration=end-start)
        edits=replace(edits,sounds=tuple(cues))
    else:raise ValueError('Open clip properties to adjust this item.')
    edits.validate(media)
    from .reactions import validate_cues
    validate_cues(edits.sounds,edits.overlays,total)
    return replace(state,edits=edits)


def remove_blocks(state, keys, media):
    keys=set(keys);edits=state.edits
    edits=replace(edits,text=replace(edits.text,captions=tuple(c for i,c in enumerate(edits.text.captions) if ('caption',i) not in keys)),
                  sounds=tuple(c for i,c in enumerate(edits.sounds) if ('sound',i) not in keys),
                  overlays=tuple(c for i,c in enumerate(edits.overlays) if ('overlay',i) not in keys))
    edits.validate(media)
    return replace(state,edits=edits)
