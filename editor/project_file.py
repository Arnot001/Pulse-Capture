"""Versioned, atomic edit-project persistence. Explicit type registry; no code loading."""
from dataclasses import fields, is_dataclass
import json
import os
from pathlib import Path
from .models import MediaInfo, TrimRange
from .sequence import SourceClip, validate_sequence
from .edit_history import EditSnapshot
from .transforms import EditOptions, Crop, Branding
from .cuts import CutPlan, CutRange
from .text_overlay import TextOverlay, Caption
from .typography import CaptionStyle
from .privacy import Privacy, PrivacyMask, Rect
from .music import Music
from .polish import Zoom, Fade
from .crop_motion import CropMotion, CropKeyframe
from .reactions import SoundCue, VisualCue
from .commentary import CommentaryClip
from .imported_media import MediaClip
from .narration import Narration

TYPES={cls.__name__:cls for cls in (MediaInfo,TrimRange,SourceClip,EditSnapshot,EditOptions,
    Crop,Branding,CutPlan,CutRange,TextOverlay,Caption,CaptionStyle,Privacy,PrivacyMask,Rect,
    Music,Zoom,Fade,CropMotion,CropKeyframe,SoundCue,VisualCue,CommentaryClip,MediaClip,Narration)}


def encode(value):
    if isinstance(value,Path):return {'path':str(value.resolve())}
    if is_dataclass(value):return {'type':type(value).__name__,'values':{f.name:encode(getattr(value,f.name)) for f in fields(value)}}
    if isinstance(value,(tuple,list)):return [encode(v) for v in value]
    return value


def decode(value):
    if isinstance(value,list):return tuple(decode(v) for v in value)
    if isinstance(value,dict):
        if set(value)=={'path'} and isinstance(value['path'],str):return Path(value['path'])
        if set(value)!={'type','values'} or value['type'] not in TYPES or not isinstance(value['values'],dict):
            raise ValueError('Unsupported project data.')
        cls=TYPES[value['type']]
        if set(value['values'])-{f.name for f in fields(cls)}:raise ValueError('Project contains unsupported settings.')
        return cls(**{k:decode(v) for k,v in value['values'].items()})
    return value


def save_project(path,media,state):
    target=Path(path)
    sources=[media.path]+[c.media.path for c in state.edits.sequence]
    if target.resolve() in [p.resolve() for p in sources]:raise ValueError('Save projects separately from source videos.')
    state.edits.validate(media);state.cuts.validate_selection(media,state.trim)
    data={'format':'pulse-edit','version':2,'media':encode(media),'state':encode(state)}
    temp=target.with_name(target.name+'.tmp')
    try:
        temp.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
        os.replace(temp,target)
    finally:
        if temp.exists():temp.unlink()


def load_project(path):
    path=Path(path)
    if path.stat().st_size>8*1024*1024:raise ValueError('Project file is too large.')
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        if data.get('format')!='pulse-edit' or data.get('version') not in (1,2):raise ValueError('Choose a Pulse edit project. Existing Auto Edit plans open in Auto Edit.')
        media,state=decode(data['media']),decode(data['state'])
        if not isinstance(media,MediaInfo) or not isinstance(state,EditSnapshot):raise ValueError('Invalid project state.')
        media.validate()
        if state.edits.sequence:
            validate_sequence(state.edits.sequence,True)
            if abs(sum(c.duration for c in state.edits.sequence)-media.duration)>.001:raise ValueError('Project clip duration does not match its timeline.')
        elif not media.path.is_file():raise ValueError(f'Missing source video: {media.path}')
        state.edits.validate(media);state.cuts.validate_selection(media,state.trim)
        return media,state
    except (KeyError,TypeError,AttributeError,RecursionError,json.JSONDecodeError) as exc:
        raise ValueError(f'Invalid project file: {exc}') from exc
