"""Closed, local-only Pulse Edit Plan v1/v2. All times are seconds, never expressions."""
import json
import math
from pathlib import Path
import re

from .cuts import CutPlan
from .models import TrimRange
from .polish import SPEEDS, ZOOM_FACTORS
from .text_overlay import Caption, TextOverlay, text_geometry
from .transforms import EditOptions

MAX_PLAN_BYTES = 256_000
TRANSITIONS = ('cut', 'dissolve', 'fade_black')
ANIMATIONS = ('none', 'fade', 'slide', 'typewriter', 'pop')


def fields(value, required, optional=(), where='plan'):
    if type(value) is not dict:
        raise ValueError(f'{where}: expected an object.')
    missing = set(required) - value.keys()
    unknown = value.keys() - set(required) - set(optional)
    if missing or unknown:
        raise ValueError(f'{where}: missing {sorted(missing)}; unsupported fields {sorted(unknown)}.')


def number(value, low, high, where):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{where}: expected a finite number from {low:g} to {high:g}.')
    return value


def choice(value, choices, where):
    if type(value) is not str or value not in choices:
        raise ValueError(f'{where}: supported values are {", ".join(choices)}.')


def text(value, limit, where, empty=False):
    if (type(value) is not str or len(value) > limit or (not empty and not value.strip())
            or any((ord(c) < 32 and c != '\n') or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise ValueError(f'{where}: expected plain text, maximum {limit} characters.')


def frame_duration(value, where):
    number(value, 1/30, 180, where)
    if abs(value*30-round(value*30)) > .00003:
        raise ValueError(f'{where}: output durations must be multiples of 1/30 second.')


def element_duration(item, freeze_default=1.8):
    return ((item['end']-item['start'])/item.get('speed', 1)
            if item['kind'] == 'shot' else item.get('duration', freeze_default))


def timeline_positions(plan):
    """Transitions overlap adjacent elements; captions use this output clock."""
    cursor = 0.
    result = []
    for item in plan['timeline']:
        cursor -= item.get('transition', {}).get('duration', 0)
        end = cursor + element_duration(item, plan.get('freeze_duration', 1.8))
        result.append((cursor, end))
        cursor = end
    return result


def validate_pulse_plan(plan, media):
    media.validate()
    fields(plan, ('format', 'version', 'title', 'source', 'output', 'timeline', 'captions'),
           ('style', 'notes') + (('sfx', 'overlays', 'caption_theme', 'freeze_duration') if plan.get('version') == 2 else ()))
    if plan['format'] != 'pulse-edit-plan' or type(plan['version']) is not int or plan['version'] not in (1, 2):
        raise ValueError('Supported format: pulse-edit-plan, version: 1 or 2.')
    v2 = plan['version'] == 2
    if v2:
        from .typography import THEMES
        choice(plan.get('caption_theme', 'Comedy Bold'), THEMES, 'caption_theme')
        frame_duration(plan.get('freeze_duration', 1.8), 'freeze_duration')
    text(plan['title'], 90, 'title')
    choice(plan.get('style', 'News/Preview'), ('News/Preview', 'Gaming', 'Comedy / Roast'), 'style')
    text(plan.get('notes', ''), 4000, 'notes', empty=True)
    source = plan['source']
    fields(source, ('name', 'sha256', 'duration', 'width', 'height', 'fps'), where='source')
    if source['name'] != media.path.name:
        raise ValueError('Source filename does not match the open recording.')
    if type(source['sha256']) is not str or not re.fullmatch('[a-f0-9]{64}', source['sha256']):
        raise ValueError('source.sha256 must be a lowercase SHA-256 fingerprint.')
    for key, actual in (('duration', media.duration), ('fps', media.fps),
                        ('width', media.width), ('height', media.height)):
        number(source[key], .001, 1_000_000, f'source.{key}')
        tolerance = .05 if key == 'duration' else .001 if key == 'fps' else 0
        if abs(source[key]-actual) > tolerance:
            raise ValueError(f'Source {key} does not match the open recording.')
    output = plan['output']
    fields(output, ('width', 'height', 'fps', 'framing', 'background'), where='output')
    if any(type(output[k]) is not int or output[k] != v
           for k, v in (('width', 1080), ('height', 1920), ('fps', 30))):
        raise ValueError('v1 output is 1080 × 1920 at 30 fps, H.264/AAC MP4.')
    choice(output['framing'], ('full_frame', 'crop_to_fill'), 'output.framing')
    choice(output['background'], ('dark',), 'output.background')
    items = plan['timeline']
    if type(items) is not list or not 1 <= len(items) <= 32:
        raise ValueError('timeline: use 1–32 shot, freeze or title elements.')
    footage = False
    for index, item in enumerate(items):
        where = f'timeline[{index}]'
        if type(item) is not dict:
            raise ValueError(f'{where}: expected an object.')
        kind = item.get('kind')
        choice(kind, ('shot', 'freeze', 'title'), where+'.kind')
        common = ('at', 'transition', 'commentary', 'role') + (('effect',) if v2 and kind != 'title' else ())
        if 'effect' in item:
            choice(item['effect'], ('punch_zoom','shake','scratch','glitch'), where+'.effect')
        if kind == 'shot':
            fields(item, ('kind', 'start', 'end'), common + ('speed', 'volume', 'zoom', 'start_frame', 'end_frame'), where)
            number(item['start'], 0, media.duration, where+'.start')
            number(item['end'], 0, media.duration, where+'.end')
            TrimRange(item['start'], item['end']).validate(media)
            speed = number(item.get('speed', 1), .5, 4, where+'.speed')
            if speed not in SPEEDS:
                raise ValueError(f'{where}: unsupported speed.')
            number(item.get('volume', 1), 0, 2, where+'.volume')
            for key in ('start', 'end'):
                if key+'_frame' in item:
                    frame = item[key+'_frame']
                    if type(frame) is not int or frame < 0 or abs(frame/media.fps-item[key]) > .5/media.fps:
                        raise ValueError(f'{where}.{key}_frame disagrees with its timestamp.')
            footage = True
        elif kind == 'freeze':
            fields(item, ('kind', 'source_time') if v2 else ('kind', 'source_time', 'duration'),
                   common + ('zoom', 'duration') if v2 else common + ('zoom',), where)
            number(item['source_time'], 0, max(0, media.duration-1/media.fps), where+'.source_time')
            footage = True
        else:
            fields(item, ('kind', 'text', 'duration'), common + ('font_size', 'animation'), where)
            text(item['text'], 160, where+'.text')
            if item['text'].count('\n') > 2:
                raise ValueError(f'{where}: use at most three title lines.')
            if type(item.get('font_size', 64)) is not int:
                raise ValueError(f'{where}.font_size: use whole pixels.')
            number(item.get('font_size', 64), 24, 120, where+'.font_size')
            choice(item.get('animation', 'fade'), ANIMATIONS, where+'.animation')
            # Bound text to the safe title area without silently changing font size.
            if max(len(line) for line in item['text'].split('\n')) * item.get('font_size', 64) > 864:
                raise ValueError(f'{where}: title line too long for font_size; add line breaks or reduce it.')
        frame_duration(element_duration(item, plan.get('freeze_duration', 1.8)), where+'.duration')
        if 'zoom' in item:
            zoom = item['zoom']
            fields(zoom, ('factor', 'x', 'y'), where=where+'.zoom')
            number(zoom['factor'], 1.25, 2, where+'.zoom.factor')
            if zoom['factor'] not in ZOOM_FACTORS:
                raise ValueError(f'{where}: zoom factor must be 1.25, 1.5 or 2.')
            for key in ('x', 'y'):
                number(zoom[key], 0, 1, where+'.zoom.'+key)
        text(item.get('commentary', ''), 2000, where+'.commentary', empty=True)
        choice(item.get('role', 'shot'), ('shot', 'setup', 'reveal', 'replay', 'punchline', 'outro'), where+'.role')
        if 'transition' in item:
            transition = item['transition']
            fields(transition, ('type', 'duration'), where=where+'.transition')
            choice(transition['type'], TRANSITIONS, where+'.transition.type')
            duration = number(transition['duration'], 0, 1, where+'.transition.duration')
            if transition['type'] == 'cut':
                if duration != 0:
                    raise ValueError('A hard cut has duration 0.')
            else:
                frame_duration(duration, where+'.transition.duration')
                if not index or duration > min(element_duration(items[index-1], plan.get('freeze_duration', 1.8)), element_duration(item, plan.get('freeze_duration', 1.8)))/2:
                    raise ValueError('A transition needs two adjacent elements and at most half of each duration.')
    if not footage:
        raise ValueError('Include at least one source shot or freeze-frame.')
    positions = timeline_positions(plan)
    duration = positions[-1][1]
    if duration > 180:
        raise ValueError('The complete output must be at most 180 seconds.')
    for item, (start, _) in zip(items, positions):
        if 'at' in item:
            number(item['at'], 0, 180, 'timeline.at')
            if abs(item['at']-start) > .00001:
                raise ValueError(f'Element at={item["at"]} must start at {start:.6f} on the output timeline.')
    captions = plan['captions']
    if type(captions) is not list or len(captions) > 80:
        raise ValueError('captions: use at most 80 cues.')
    for cue in captions:
        fields(cue, ('start', 'end', 'text', 'zone', 'basis'), ('evidence', 'typography') if v2 else ('evidence',), 'caption')
        number(cue['start'], 0, duration, 'caption.start')
        number(cue['end'], 0, duration, 'caption.end')
        text(cue['text'], 160, 'caption.text')
        choice(cue['zone'], ('top', 'bottom'), 'caption.zone')
        choice(cue['basis'], ('observation', 'joke', 'verified', 'unverified'), 'caption.basis')
        text(cue.get('evidence', ''), 500, 'caption.evidence', empty=True)
        if cue['basis'] == 'verified' and not cue.get('evidence', '').strip():
            raise ValueError('Verified captions require an evidence note; jokes are not confirmed bugs.')
        style = caption_style(plan, cue)
        Caption(cue['start'], cue['end'], cue['text'], cue['zone'].title(), style).validate()
        if style and style.highlight and style.highlight not in cue['text']:
            raise ValueError('Caption highlight must occur in its text.')
        text_geometry(1080, 1920, TextOverlay(True, cue['text'], position=cue['zone'].title(), safe_area=True))
    if v2:
        from .reactions import validate_cues
        sounds, overlays = reaction_cues(plan)
        validate_cues(sounds, overlays, duration)
    return plan


def caption_style(plan, cue):
    if plan['version'] == 1:
        return None
    from dataclasses import asdict
    from .typography import CaptionStyle, theme_style
    props = cue.get('typography', {})
    fields(props, (), tuple(CaptionStyle.__dataclass_fields__), 'caption.typography')
    style = asdict(theme_style(props.get('theme', plan.get('caption_theme', 'Comedy Bold'))))
    style.update(props)
    result = CaptionStyle(**style)
    result.validate()
    return result


def reaction_cues(plan):
    from .reactions import SoundCue, VisualCue
    result = []
    for key, model, required, limit in (('sfx', SoundCue, ('asset_id','at'),64),
                                        ('overlays', VisualCue, ('kind','asset_id','start','end'),24)):
        values = plan.get(key, [])
        if type(values) is not list or len(values)>limit:
            raise ValueError(f'{key}: expected an array with at most {limit} cues.')
        cues = []
        for value in values:
            fields(value, required, tuple(model.__dataclass_fields__), key)
            cue = model(**value)
            cue.validate()
            cues.append(cue)
        result.append(tuple(cues))
    return tuple(result)


def parse_pulse_plan(raw):
    if len(raw.encode('utf-8')) > MAX_PLAN_BYTES:
        raise ValueError('Pulse plans must be at most 256 KB.')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON field: {key}.')
            result[key] = value
        return result
    def constant(value):
        raise ValueError(f'Invalid JSON number: {value}.')
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=constant)
    except (RecursionError, json.JSONDecodeError) as exc:
        raise ValueError('Malformed Pulse plan JSON.') from exc
    if type(value) is not dict or value.get('format') != 'pulse-edit-plan':
        raise ValueError('Choose a versioned pulse-edit-plan JSON file.')
    return value


def read_pulse_plan(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_PLAN_BYTES+1)
    if len(raw) > MAX_PLAN_BYTES:
        raise ValueError('Pulse plans must be at most 256 KB.')
    try:
        return parse_pulse_plan(raw.decode('utf-8-sig'))
    except UnicodeError as exc:
        raise ValueError('Pulse plans must contain UTF-8 JSON.') from exc


def source_identity(media, cancel):
    from .auto_analysis import fingerprint
    return dict(name=media.path.name, duration=media.duration, width=media.width,
                height=media.height, fps=media.fps, sha256=fingerprint(media.path, cancel))


def verify_source(plan, media, cancel):
    from .auto_analysis import fingerprint
    validate_pulse_plan(plan, media)
    if fingerprint(media.path, cancel) != plan['source']['sha256']:
        raise ValueError('Source SHA-256 does not match. This plan belongs to a different recording.')


def pulse_editor_state(plan, assembled_media):
    if assembled_media is None:
        raise ValueError('Assemble the Pulse timeline before opening its editor state.')
    assembled_media.validate()
    duration = timeline_positions(plan)[-1][1]
    if ((assembled_media.width, assembled_media.height) != (1080, 1920)
            or abs(assembled_media.duration-duration) > .08):
        raise ValueError('Assembled media does not match the Pulse output timeline.')
    captions = tuple(Caption(c['start'], c['end'], c['text'], c['zone'].title(), caption_style(plan, c))
                     for c in plan['captions'] if c['basis'] != 'unverified')
    sounds, overlays = reaction_cues(plan)
    edits = EditOptions(text=TextOverlay(captions=captions, safe_area=True), sounds=sounds, overlays=overlays)
    trim, cuts = TrimRange(0, assembled_media.duration), CutPlan()
    edits.validate(assembled_media)
    cuts.validate_selection(assembled_media, trim)
    return trim, cuts, edits


def starter_plan(media, identity):
    duration = min(5, math.floor(media.duration*30)/30)
    if duration < 1/30:
        raise ValueError('Recording must contain at least one output frame.')
    return {'format': 'pulse-edit-plan', 'version': 1, 'title': 'Review this moment',
            'style': 'News/Preview', 'source': identity,
            'output': dict(width=1080, height=1920, fps=30, framing='full_frame', background='dark'),
            'timeline': [{'kind': 'title', 'text': 'TAKE A LOOK', 'duration': 1},
                         {'kind': 'shot', 'start': 0, 'end': duration},
                         {'kind': 'title', 'text': 'YOUR VERDICT?', 'duration': 1}],
            'captions': []}
