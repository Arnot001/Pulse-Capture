"""Offline caption styling checks: no network, external fonts, or video rendering."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from editor.caption_tools import load_caption_preference, save_caption_preference
from editor.text_overlay import Caption
from editor.typography import (
    CaptionStyle, FONT_FAMILIES, THEMES, ass_background_colour,
    styled_filter, theme_style,
)


def test_every_supported_font_and_preset_validates():
    for family in FONT_FAMILIES:
        CaptionStyle(font_family=family).validate()
    for name in THEMES:
        style = theme_style(name)
        assert style.theme == name or name == 'Comedy Bold'
        style.validate()


@pytest.mark.parametrize('changes', [
    {'font_family': 'Untrusted,ASS,Font'},
    {'font_family': ''},
    {'background_colour': 'red'},
    {'background_colour': '#FFF'},
    {'background_opacity': -0.01},
    {'background_opacity': 1.01},
    {'background_enabled': 'yes'},
    {'bold': 1},
    {'x_offset': -0.5},
    {'y_offset': 0.5},
])
def test_rejects_invalid_caption_style(changes):
    with pytest.raises(ValueError):
        replace(CaptionStyle(), **changes).validate()


def test_ass_alpha_colours():
    assert ass_background_colour('#FF0000', 1) == '&H000000FF&'
    assert ass_background_colour('#0000FF', 0) == '&HFFFF0000&'


def test_style_is_consistent_for_preview_and_export(tmp_path):
    style = CaptionStyle(
        theme='Pulse Neon', font_family='Arial', colour='#27DEF5',
        background_enabled=True, background_colour='#113355',
        background_opacity=.5, bold=False, x_offset=.1, y_offset=-.1,
        animation='none',
    )
    caption = Caption(0, 3, 'Pulse Social tutorial', style=style)
    resources = SimpleNamespace(temp=SimpleNamespace(name=str(tmp_path)))
    export_filter = styled_filter(1080, 1920, caption, style, resources, [(0, 3)])
    preview_filter = styled_filter(1080, 1920, caption, style, resources, [(0, 3)], sample_time=1.0)
    assert 'ass=filename=' in export_filter
    assert 'ass=filename=' in preview_filter
    export_ass, preview_ass = sorted(tmp_path.glob('style-*.ass'))
    export = export_ass.read_text(encoding='utf-8')
    preview = preview_ass.read_text(encoding='utf-8')
    assert export == preview  # Same ASS definitions irrespective of preview timestamps.
    style_row = next(line for line in export.splitlines() if line.startswith('Style: Pulse,'))
    parts = style_row.split(',')
    assert parts[1] == 'Arial'
    assert parts[7] == '0'    # Non-bold text
    assert parts[15] == '3'   # Opaque-box border style, alpha is in BackColour
    assert '&H' in parts[6]  # Background colour is encoded for ASS
    assert 'Dialogue: 0,' in export


def test_style_preferences_roundtrip_and_invalid_file_recovery(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    style = theme_style('Pulse Neon')
    save_caption_preference(style)
    path = tmp_path / 'Pulse Capture' / 'caption_style.json'
    assert path.is_file()
    assert load_caption_preference() == style
    path.write_text('{"background_enabled":"not-bool"}', encoding='utf-8')
    assert load_caption_preference() == CaptionStyle()
