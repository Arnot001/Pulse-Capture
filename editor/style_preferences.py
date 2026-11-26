"""Shared caption/text style storage; existing filenames and records remain valid."""
from dataclasses import asdict
import json
import os
from pathlib import Path
from .typography import CaptionStyle, THEMES


def _preferences_path():
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Pulse Capture' / 'caption_style.json'


def load_caption_preference():
    """Style preferences only; never touch capture projects or stored media."""
    try:
        data = json.loads(_preferences_path().read_text(encoding='utf-8'))
        style = CaptionStyle(**data)
        style.validate()
        return style
    except (OSError, TypeError, ValueError, KeyError):
        return CaptionStyle()


def save_caption_preference(style):
    """Best-effort atomic save; a locked settings directory must not block edits."""
    if style is None:
        return
    style.validate()
    try:
        path = _preferences_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(asdict(style), indent=2), encoding='utf-8')
        os.replace(temp, path)
    except OSError:
        pass



def load_style_library():
    result = {'presets': {}, 'recent': []}
    try:
        data = json.loads(_preferences_path().with_name('caption_presets.json').read_text(encoding='utf-8'))
        for name, values in data.get('presets', {}).items():
            if not isinstance(name, str) or name in THEMES: continue
            try:
                CaptionStyle(**values).validate()
                result['presets'][name] = values
            except (TypeError, ValueError): pass
        import re
        result['recent'] = [c for c in data.get('recent', []) if isinstance(c,str) and re.fullmatch('#[0-9A-Fa-f]{6}',c)][:12]
        from .caption_fonts import safe_family
        for key, limit in (('recent_fonts',12),('favourite_fonts',100)):
            if key in data:
                result[key] = list(dict.fromkeys(name for name in data[key] if safe_family(name)))[:limit]
    except (OSError, ValueError, TypeError, AttributeError): pass
    return result


def save_style_library(data):
    path = _preferences_path().with_name('caption_presets.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    os.replace(temp, path)


def remember_font(name, favourite=False):
    from .caption_fonts import safe_family
    if not safe_family(name):return
    data = load_style_library()
    key = 'favourite_fonts' if favourite else 'recent_fonts'
    values = data.get(key, [])
    if favourite:
        values = [v for v in values if v != name] if name in values else [*values, name]
    else:
        values = [name, *[v for v in values if v != name]][:12]
    data[key] = values[:100]
    save_style_library(data)


