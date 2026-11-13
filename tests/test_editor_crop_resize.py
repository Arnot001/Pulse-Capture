"""Ratio-locked crop resizing and existing Shorts keyframe compatibility."""
from dataclasses import replace
from pathlib import Path
import unittest

from editor.crop_motion import CropMotion
from editor.ffmpeg_export import build_export_command
from editor.models import MediaInfo, TrimRange
from editor.preview import preview_command
from editor.transforms import EditOptions, SHORTS_FORMAT


class CropResizeTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 10, 1920, 1080, 30, True)
        self.base = EditOptions().with_format(self.media, SHORTS_FORMAT)

    def test_all_four_handles_keep_exact_ratio_and_opposite_anchor(self):
        crop = self.base.crop
        cases = {
            'nw': (crop.x + crop.width - 306, crop.y + crop.height - 544),
            'ne': (crop.x + 306, crop.y + crop.height - 544),
            'sw': (crop.x + crop.width - 306, crop.y + 544),
            'se': (crop.x + 306, crop.y + 544),
        }
        for corner, (x, y) in cases.items():
            with self.subTest(corner=corner):
                small = crop.resized(self.media, corner, x, y)
                small.validate(self.media)
                self.assertEqual((small.width, small.height), (306, 544))
                self.assertEqual(small.width * 16, small.height * 9)
                self.assertEqual(small.x + (small.width if 'w' in corner else 0),
                                 crop.x + (crop.width if 'w' in corner else 0))
                self.assertEqual(small.y + (small.height if 'n' in corner else 0),
                                 crop.y + (crop.height if 'n' in corner else 0))
                self.assertEqual(self.base.__class__(preset=SHORTS_FORMAT, crop=small).encoded_size(self.media),
                                 (1080, 1920))

    def test_growth_clamps_to_source_and_rejects_invalid_input(self):
        crop = self.base.crop
        small = crop.resized(self.media, 'se', crop.x + 306, crop.y + 544)
        grown = small.resized(self.media, 'se', 99999, 99999)
        grown.validate(self.media)
        self.assertEqual((grown.width, grown.height), (594, 1056))
        tiny = crop.resized(self.media, 'se', crop.x + 1, crop.y + 1)
        self.assertGreaterEqual(min(tiny.width, tiny.height), 64)
        for corner, x, y in [('nope', 100, 100), ('se', float('nan'), 100),
                             ('se', 100, float('inf'))]:
            with self.assertRaises(ValueError):
                crop.resized(self.media, corner, x, y)

    def test_resizing_horizontal_square_and_portrait_sources(self):
        for preset in ('16:9 Landscape', '1:1 Square', SHORTS_FORMAT):
            for media in (self.media, replace(self.media, width=1080, height=1920)):
                crop = EditOptions().with_format(media, preset).crop
                small = crop.resized(media, 'se', crop.x+crop.width*.6,
                                     crop.y+crop.height*.6)
                edits = EditOptions().with_format(media, preset)
                resized = replace(edits, crop=small)
                resized.validate(media)
                self.assertLessEqual(small.width, crop.width)
                self.assertLessEqual(small.height, crop.height)
                self.assertEqual(small.width * crop.height, small.height * crop.width)

    def test_keyframe_reframe_preserves_source_time_and_centres(self):
        crop = self.base.crop
        left = crop.moved(self.media, 0, 0)
        right = crop.moved(self.media, 1326, 24)
        motion = CropMotion().at(self.media, left, 1).at(self.media, right, 9)
        small = crop.resized(self.media, 'se', crop.x + 306, crop.y + 544)
        changed = motion.reframed(self.media, crop, small)
        edits = replace(self.base, crop=small, crop_motion=changed)
        edits.validate(self.media)
        self.assertEqual([k.time for k in changed.keyframes], [1, 9])
        self.assertTrue(all(k.x % 2 == 0 and k.y % 2 == 0
                            for k in changed.keyframes))
        self.assertGreater(edits.crop_at(self.media, 1).x, 0)
        self.assertEqual(edits.crop_at(self.media, 9).x, right.x + 144)
        self.assertEqual(edits.encoded_size(self.media), (1080, 1920))

    def test_resized_static_preview_matches_export_dimensions(self):
        crop = self.base.crop.resized(self.media, 'se',
                                       self.base.crop.x+306,
                                       self.base.crop.y+544)
        edits = replace(self.base, crop=crop)
        trim = TrimRange(1, 3)
        command = build_export_command('ffmpeg', self.media, trim, 'out.mp4', edits)
        filters = command[command.index('-vf')+1]
        self.assertIn(f'crop={crop.width}:{crop.height}:{crop.x}:{crop.y}', filters)
        self.assertIn('scale=1080:1920', filters)
        preview = preview_command('ffmpeg', self.media, 1, 600, 400, edits,
                                  False, trim=trim)
        self.assertIn(f'crop={crop.width}:{crop.height}:{crop.x}:{crop.y}',
                      preview[preview.index('-vf')+1])


if __name__ == '__main__':
    unittest.main()
