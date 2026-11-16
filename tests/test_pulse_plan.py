import copy
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest

from editor.auto_plan import editor_state, validate_plan
from editor.models import MediaInfo, TrimRange
from editor.pulse_plan import (parse_pulse_plan, read_pulse_plan, source_identity,
                               starter_plan, timeline_positions, verify_source)
from editor.transforms import EditOptions, FULL_FRAME_FORMAT
from editor.ffmpeg_export import build_export_command
from editor.preview import preview_command
from tests.test_auto_edit import candidate


class PulsePlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name)/'fixture.mp4'
        self.source.write_bytes(b'fixture identity')
        self.media = MediaInfo(self.source, 8, 640, 360, 30, True)
        self.cancel = threading.Event()
        self.plan = starter_plan(self.media, source_identity(self.media, self.cancel))

    def test_external_json_validates_and_verifies_source(self):
        path = self.source.with_suffix('.json')
        path.write_text(json.dumps(self.plan), encoding='utf-8')
        plan = read_pulse_plan(path)
        self.assertEqual(validate_plan(plan, self.media), self.plan)
        verify_source(plan, self.media, self.cancel)
        self.source.write_bytes(b'changed recording')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            verify_source(plan, self.media, self.cancel)

    def test_reordered_replay_freeze_and_transition_output_clock(self):
        self.plan['timeline'] = [dict(kind='shot', start=6, end=8),
                                 dict(kind='shot', start=0, end=1, speed=.5),
                                 dict(kind='shot', start=6, end=8, at=3.5,
                                      transition=dict(type='dissolve', duration=.5)),
                                 dict(kind='freeze', source_time=7, duration=1, at=5.5)]
        validate_plan(self.plan, self.media)
        self.assertEqual(timeline_positions(self.plan), [(0, 2), (2, 4), (3.5, 5.5), (5.5, 6.5)])

    def test_caption_zones_claims_and_scripts_survive_conversion(self):
        self.plan['captions'] = [dict(start=1, end=2, text='Visible detail', zone='top', basis='observation'),
                                 dict(start=3, end=4, text='Pocket dimension?', zone='bottom', basis='joke'),
                                 dict(start=4, end=5, text='A confirmed bug?', zone='top', basis='unverified')]
        self.plan['timeline'][1]['commentary'] = 'Record this later.'
        assembled = MediaInfo(self.source.parent/'review.mp4', 7, 1080, 1920, 30, True)
        trim, cuts, edits = editor_state(self.plan, self.media, assembled_media=assembled)
        self.assertEqual(trim, TrimRange(0, 7))
        self.assertEqual(cuts.kept_duration(trim), 7)
        self.assertEqual([c.position for c in edits.text.captions], ['Top', 'Bottom'])
        self.assertFalse(edits.music.enabled)
        with self.assertRaisesRegex(ValueError, 'Assemble'):
            editor_state(self.plan, self.media)
        with self.assertRaises(ValueError):
            editor_state(self.plan, self.media, assembled_media=replace(assembled, duration=8))

    def test_malformed_unsupported_and_unsafe_instructions_rejected(self):
        changes = [lambda p: p.update(command='touch source'),
                   lambda p: p.update(version=True),
                   lambda p: p['source'].update(duration=10),
                   lambda p: p['source'].update(name='other.mp4'),
                   lambda p: p['source'].update(fps=60),
                   lambda p: p['output'].update(background='blur'),
                   lambda p: p['output'].update(width=720),
                   lambda p: p['timeline'][1].update(start=-1),
                   lambda p: p['timeline'][1].update(end=100),
                   lambda p: p['timeline'][1].update(start=True),
                   lambda p: p['timeline'][1].update(speed=float('nan')),
                   lambda p: p['timeline'][1].update(volume=float('inf')),
                   lambda p: p['timeline'][1].update(filter='movie=secret'),
                   lambda p: p['timeline'][1].update(zoom=dict(factor=1.5, x=2, y=0)),
                   lambda p: p['timeline'][1].update(start_frame=15),
                   lambda p: p['timeline'][1].update(at=9),
                   lambda p: p['timeline'][1].update(transition=dict(type='glitch', duration=.1)),
                   lambda p: p['timeline'][1].update(transition=dict(type='cut', duration=.1)),
                   lambda p: p['timeline'][0].update(transition=dict(type='dissolve', duration=.2)),
                   lambda p: p['timeline'][0].update(duration=.111),
                   lambda p: p['timeline'][0].update(font_size=500),
                   lambda p: p['timeline'][0].update(animation='shell'),
                   lambda p: p.update(captions=[dict(start=1, end=2, text='Bug', zone='top', basis='verified')]),
                   lambda p: p.update(captions=[dict(start=1, end=200, text='Hello', zone='top', basis='joke')])]
        for change in changes:
            plan = copy.deepcopy(self.plan)
            change(plan)
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                validate_plan(plan, self.media)

    def test_duplicate_fields_nonfinite_deep_and_oversize_json(self):
        for raw in ('{"format":"pulse-edit-plan","version":1,"version":2}',
                    '{"format":"pulse-edit-plan","version":NaN}', '['*2000+']'*2000,
                    ' '*256001, '[]', '{broken'):
            with self.subTest(raw=raw[:100]), self.assertRaises(ValueError):
                parse_pulse_plan(raw)

    def test_full_frame_export_and_preview_share_no_crop_layout(self):
        edits = EditOptions().with_format(self.media, FULL_FRAME_FORMAT)
        self.assertIsNone(edits.crop)
        self.assertFalse(edits.crop_motion.keyframes)
        self.assertEqual(edits.encoded_size(self.media), (1080, 1920))
        command = build_export_command('ffmpeg', self.media, TrimRange(0, 2), 'out.mp4', edits)
        layout = command[command.index('-vf')+1]
        self.assertNotIn('crop=', layout)
        self.assertIn('force_original_aspect_ratio=decrease', layout)
        preview = preview_command('ffmpeg', self.media, 1, 320, 640, edits, False)
        self.assertTrue(preview[preview.index('-vf')+1].startswith(layout))

    def test_news_and_comedy_default_full_frame_gaming_retains_crop(self):
        for style in ('News/Preview', 'Comedy / Roast', 'Gaming'):
            _, _, edits = editor_state(candidate(0, 5), self.media, style=style)
            self.assertEqual(edits.crop is None, style != 'Gaming')


if __name__ == '__main__':
    unittest.main()
