"""Strict Auto Edit plans, translated into the existing non-destructive editor."""
from dataclasses import dataclass, replace
import math
import textwrap

from .crop_motion import CropKeyframe, CropMotion
from .cuts import CutPlan, CutRange
from .models import TrimRange
from .text_overlay import TextOverlay, Caption
from .transforms import EditOptions, SHORTS_FORMAT

STYLES = ('Gaming', 'News/Preview', 'Funny Moments')
PLAN_VERSION = 1


@dataclass(frozen=True)
class AutoOptions:
    count: int = 3
    style: str = 'News/Preview'
    minimum: float = 20
    maximum: float = 35

    def validate(self):
        if type(self.count) is not int or not 1 <= self.count <= 3 or self.style not in STYLES:
            raise ValueError('Choose 1–3 Shorts and a listed editing style.')
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (self.minimum, self.maximum)):
            raise ValueError('Enter valid target durations.')
        if not 5 <= self.minimum <= self.maximum <= 60:
            raise ValueError('Use durations from 5 to 60 seconds, with minimum no greater than maximum.')


def _object(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties),
            'additionalProperties': False}


def _array(items, limit):
    return {'type': 'array', 'items': items, 'maxItems': limit}


NUMBER = {'type': 'number'}
STRING = {'type': 'string'}
SHOT_SCHEMA = _object({'start': NUMBER, 'end': NUMBER, 'focus_x': NUMBER, 'focus_y': NUMBER,
                       'end_focus_x': NUMBER, 'end_focus_y': NUMBER})
CAPTION_SCHEMA = _object({'start': NUMBER, 'end': NUMBER, 'text': STRING,
                          'basis': {'type': 'string', 'enum': ['observed', 'question', 'verify']}})
SHORT_SCHEMA = _object({'title': STRING, 'description': STRING, 'rationale': STRING,
                        'verification': _array(STRING, 8), 'shots': _array(SHOT_SCHEMA, 8),
                        'captions': _array(CAPTION_SCHEMA, 16)})
PLAN_SCHEMA = _object({'shorts': _array(SHORT_SCHEMA, 3)})


def check_schema(value, schema, where='plan'):
    """Small closed-schema validator. Reject coercion, NaN and unknown fields."""
    kind = schema['type']
    if kind == 'object':
        if type(value) is not dict or set(value) != set(schema['properties']):
            raise ValueError(f'{where}: missing or unexpected fields.')
        for key, sub in schema['properties'].items():
            check_schema(value[key], sub, f'{where}.{key}')
    elif kind == 'array':
        if type(value) is not list or len(value) > schema['maxItems']:
            raise ValueError(f'{where}: too many or invalid items.')
        for item in value:
            check_schema(item, schema['items'], where)
    elif kind == 'number':
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f'{where}: expected a finite number.')
    elif kind == 'string':
        if type(value) is not str or any(ord(c) < 32 and c != '\n' for c in value):
            raise ValueError(f'{where}: invalid text.')
        if 'enum' in schema and value not in schema['enum']:
            raise ValueError(f'{where}: unknown value.')


def overlap_seconds(a, b):
    return sum(max(0, min(x['end'], y['end']) - max(x['start'], y['start']))
               for x in a['shots'] for y in b['shots'])


def validate_plan(plan, media, options):
    options.validate()
    media.validate()
    check_schema(plan, PLAN_SCHEMA)
    if not 1 <= len(plan['shorts']) <= options.count:
        raise ValueError('The plan must contain at least one Short, up to the requested count.')
    for short in plan['shorts']:
        for name, limit in (('title', 90), ('description', 800), ('rationale', 600)):
            if not short[name].strip() or len(short[name]) > limit:
                raise ValueError(f'Invalid {name} length.')
        if any(not v.strip() or len(v) > 240 for v in short['verification']):
            raise ValueError('Invalid verification note.')
        if not short['shots']:
            raise ValueError('A Short must contain footage.')
        previous, duration = -1, 0
        for shot in short['shots']:
            TrimRange(shot['start'], shot['end']).validate(media)
            if shot['end'] > media.duration or shot['start'] < previous:
                raise ValueError('Shots must be inside the source, chronological and non-overlapping.')
            if shot['end'] - shot['start'] < 1:
                raise ValueError('Keep at least one second per shot; avoid flash cuts.')
            for key in ('focus_x', 'focus_y', 'end_focus_x', 'end_focus_y'):
                if not 0 <= shot[key] <= 1:
                    raise ValueError('Crop focus must be normalized between zero and one.')
            previous = shot['end']
            duration += shot['end'] - shot['start']
        if not options.minimum - .001 <= duration <= options.maximum + .001:
            raise ValueError('The plan does not respect the selected duration.')
        previous = -1
        for cue in short['captions']:
            if not 0 <= cue['start'] < cue['end'] <= media.duration or cue['start'] < previous:
                raise ValueError('Captions must use ordered, non-overlapping source times.')
            if not any(s['start'] <= cue['start'] < cue['end'] <= s['end'] for s in short['shots']):
                raise ValueError('Keep each caption inside a selected shot.')
            if not cue['text'].strip() or len(cue['text']) > 70 or cue['end'] - cue['start'] < 1:
                raise ValueError('Keep captions short and visible for at least one second.')
            if cue['basis'] == 'verify' and not short['verification']:
                raise ValueError('Unverified captions need a verification note.')
            previous = cue['end']
    for index, short in enumerate(plan['shorts']):
        for other in plan['shorts'][:index]:
            shortest = min(sum(s['end']-s['start'] for s in x['shots']) for x in (short, other))
            if overlap_seconds(short, other) / shortest > .35:
                raise ValueError('Candidates share too much footage; make genuinely different Shorts.')
    return plan


def wrap_caption(value):
    value = ' '.join(value.split())
    width = 24
    lines = textwrap.wrap(value, width=width)
    while len(lines) > 3:
        width += 1
        lines = textwrap.wrap(value, width=width)
    return '\n'.join(lines)


def editor_state(short, media, transcript=()):
    """Source-time plans become existing trims, cuts, crop keys and captions."""
    shots = short['shots']
    trim = TrimRange(shots[0]['start'], shots[-1]['end'])
    cuts = CutPlan(tuple(CutRange(a['end'], b['start']) for a, b in zip(shots, shots[1:])
                         if b['start'] > a['end']))
    edits = EditOptions().with_format(media, SHORTS_FORMAT)
    keys = {}
    for shot in shots:
        for at, x, y in ((shot['start'], shot['focus_x'], shot['focus_y']),
                         (max(shot['start'], shot['end']-1/media.fps),
                          shot['end_focus_x'], shot['end_focus_y'])):
            crop = edits.crop.moved(media, x*media.width-edits.crop.width/2,
                                   y*media.height-edits.crop.height/2)
            keys[at] = CropKeyframe(at, crop.x, crop.y)
    captions = [Caption(c['start'], c['end'], wrap_caption(c['text']), 'Top')
                for c in short['captions'] if c['basis'] != 'verify']
    for cue in transcript:
        for shot in shots:
            start, end = max(cue['start'], shot['start']), min(cue['end'], shot['end'])
            if end-start >= .15:
                captions.append(Caption(start, end, wrap_caption(cue['text']), 'Bottom'))
    edits = replace(edits, crop_motion=CropMotion(tuple(keys[k] for k in sorted(keys))),
                    text=TextOverlay(captions=tuple(captions), safe_area=True))
    edits.validate(media)
    cuts.validate_selection(media, trim)
    return trim, cuts, edits
