"""Resizing crop handles must preserve aspect, move/crop keyframes, and export."""
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
        self.media = MediaInfo(Path('source.mp4'), 12, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 11)
        self.shorts = EditOptions().with_format(self.media, SHORTS_FORMAT)
        self.original = self.shorts.crop

    def test_each_corner_shrinks_from_the_correct_fixed_corner(self):
        old = self.original
        for corner, dx, dy in (('top-left', 120, 0), ('top-right', -120, 0),
                               ('bottom-left', 120, 0), ('bottom-right', -120, 0)):
            with self.subTest(corner=corner):
                new = old.resized(self.media, corner, dx, dy)
                self.assertLess(new.width, old.width)
                self.assertLess(new.height, old.height)
                self.assertEqual(new.width * 16, new.height * 9)
                self.assertTrue(all(value % 2 == 0 for value in
                                    (new.x, new.y, new.width, new.height)))
                self.assertEqual(new.x + new.width if corner.endswith('left') else new.x,
                                 old.x + old.width if corner.endswith('left') else old.x)
                self.assertEqual(new.y + new.height if corner.startswith('top') else new.y,
                                 old.y + old.height if corner.startswith('top') else old.y)
                new.validate(self.media)
                replace(self.shorts, crop=new).validate(self.media)

    def test_vertical_only_drag_changes_crop_and_full_outside_drag_clamps(self):
        old = self.original
        small = old.resized(self.media, 'bottom-right', 0, -200)
        self.assertLess(small.width, old.width)
        self.assertEqual(small.width*16, small.height*9)
        restored = small.resized(self.media, 'bottom-right', 10000, 10000)
        self.assertEqual(restored, old)
        tiny = old.resized(self.media, 'bottom-right', -10000, -10000)
        self.assertEqual((tiny.width, tiny.height), (18, 32))

    def test_non_shorts_format_resizes_without_distortion(self):
        landscape = EditOptions().with_format(self.media, '16:9 Landscape')
        resized = landscape.crop.resized(self.media, 'bottom-right', -300, 0)
        self.assertEqual(resized.width * 9, resized.height * 16)
        replace(landscape, crop=resized).validate(self.media)
        square = EditOptions().with_format(self.media, '1:1 Square')
        smaller = square.crop.resized(self.media, 'top-left', 90, 90)
        self.assertEqual(smaller.width, smaller.height)
        replace(square, crop=smaller).validate(self.media)

    def test_invalid_corner_and_motion_raise_without_modifying_state(self):
        for corner, dx, dy in (('centre', 30, 30),
                               ('top-left', float('nan'), 0)):
            with self.subTest(corner=corner), self.assertRaises(ValueError):
                self.original.resized(self.media, corner, dx, dy)
        self.assertEqual(self.shorts.crop, self.original)

    def test_shorts_export_resizes_to_standard_1080_by_1920(self):
        small = self.original.resized(self.media, 'top-left', 150, 0)
        edits = replace(self.shorts, crop=small)
        cmd = build_export_command('ffmpeg', self.media, self.trim, 'short.mp4', edits)
        filt = cmd[cmd.index('-vf') + 1]
        self.assertIn(f'crop={small.width}:{small.height}:{small.x}:{small.y}', filt)
        self.assertIn('scale=1080:1920:flags=lanczos', filt)
        self.assertEqual(edits.encoded_size(self.media), (1080, 1920))
        preview = preview_command('ffmpeg', self.media, 3, 600, 500, edits, False, trim=self.trim)
        self.assertIn(f'crop={small.width}:{small.height}', ' '.join(preview))

    def test_resize_preserves_moving_crop_keys_and_animation(self):
        first = self.original.moved(self.media, 0, 0)
        last = self.original.moved(self.media, 1326, 24)
        motion = CropMotion().at(self.media, first, 0).at(self.media, last, 10)
        edits = replace(self.shorts, crop_motion=motion)
        sampled = edits.crop_at(self.media, 5)
        resized = sampled.resized(self.media, 'top-left', 100, 0)
        updated = motion.resized(self.media, sampled, resized)
        edited = replace(edits, crop=resized, crop_motion=updated)
        edited.validate(self.media)
        self.assertEqual(len(edited.crop_motion.keyframes), 2)
        self.assertEqual(edited.crop_at(self.media, 5), resized)
        cmd = build_export_command('ffmpeg', self.media, self.trim, 'motion.mp4', edited)
        filt = cmd[cmd.index('-vf')+1]
        self.assertIn(f'crop={resized.width}:{resized.height}', filt)
        self.assertIn('scale=1080:1920', filt)
        self.assertIn('clip((t+1.000000000', filt)


if __name__ == '__main__':
    unittest.main()
