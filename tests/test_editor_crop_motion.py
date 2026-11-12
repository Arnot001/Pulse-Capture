"""Regression tests for source-time moving YouTube Shorts framing."""
from dataclasses import replace
from pathlib import Path
import unittest

from editor.crop_motion import CropKeyframe, CropMotion, motion_crop_filter
from editor.cuts import CutPlan, CutRange
from editor.ffmpeg_export import build_export_command
from editor.models import MediaInfo, TrimRange
from editor.polish import Zoom
from editor.preview import preview_command
from editor.privacy import Privacy, PrivacyMask, Rect
from editor.transforms import EditOptions, SHORTS_FORMAT


class CropMotionTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 10, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 9)
        self.base = EditOptions().with_format(self.media, SHORTS_FORMAT)

    def moving(self):
        left = self.base.crop.moved(self.media, 0, 0)
        right = self.base.crop.moved(self.media, 1326, 24)
        keys = CropMotion().at(self.media, left, 0).at(self.media, right, 10)
        return replace(self.base, crop_motion=keys)

    def test_sample_interpolates_even_source_coordinates(self):
        edits = self.moving()
        self.assertEqual((edits.crop_at(self.media, -1).x, edits.crop_at(self.media, -1).y), (0, 0))
        self.assertEqual((edits.crop_at(self.media, 5).x, edits.crop_at(self.media, 5).y), (664, 12))
        self.assertEqual((edits.crop_at(self.media, 20).x, edits.crop_at(self.media, 20).y), (1326, 24))
        self.assertEqual(edits.encoded_size(self.media), (1080, 1920))

    def test_save_update_delete_and_cap_keyframes(self):
        motion = CropMotion()
        crop = self.base.crop
        motion = motion.at(self.media, crop, 3.02)
        self.assertAlmostEqual(motion.keyframes[0].time, 3.0333333333)
        moved = crop.moved(self.media, 500, 10)
        motion = motion.at(self.media, moved, 3.03)
        self.assertEqual(len(motion.keyframes), 1)
        self.assertEqual(motion.keyframes[0].x, 500)
        motion = motion.at(self.media, crop, 8)
        self.assertEqual(len(motion.keyframes), 2)
        motion = motion.remove_at(self.media, crop, 8)
        self.assertEqual(len(motion.keyframes), 1)
        with self.assertRaisesRegex(ValueError, 'Move to a saved'):
            motion.remove_at(self.media, crop, 8)
        with self.assertRaisesRegex(ValueError, 'no more than'):
            CropMotion(tuple(CropKeyframe(i/10, 0, 0) for i in range(65))).validate(self.media, crop)

    def test_invalid_keys_and_incompatible_formats_are_rejected(self):
        crop = self.base.crop
        for keys in (
                (CropKeyframe(2, 1, 0),),
                (CropKeyframe(2, 2000, 0),),
                (CropKeyframe(-1, 0, 0),),
                (CropKeyframe(4, 0, 0), CropKeyframe(3, 2, 0)),
                (CropKeyframe(2, 0, 0), CropKeyframe(2, 2, 0))):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                CropMotion(keys).validate(self.media, crop)
        moving = self.moving()
        with self.assertRaisesRegex(ValueError, 'YouTube Shorts'):
            replace(moving, preset='9:16 Vertical').validate(self.media)
        self.assertEqual(moving.with_format(self.media, '1:1 Square').crop_motion, CropMotion())

    def test_privacy_masks_are_not_allowed_to_drift_with_animated_crop(self):
        moving = self.moving()
        mask = PrivacyMask('Blur', Rect(800, 200, 80, 80), 0, 8)
        with self.assertRaisesRegex(ValueError, 'Clear Privacy masks'):
            replace(moving, privacy=Privacy((mask,))).validate(self.media)

    def test_trimmed_export_uses_dynamic_source_timestamps(self):
        moving = self.moving()
        cmd = build_export_command('ffmpeg', self.media, self.trim, 'out.mp4', moving)
        self.assertIn('-vf', cmd)
        expression = cmd[cmd.index('-vf') + 1]
        self.assertIn("crop=594:1056:x='trunc(", expression)
        self.assertIn('clip((t+1.000000000-0.000000000)', expression)
        self.assertIn('scale=1080:1920', expression)
        self.assertIn('0:a:0', cmd)

    def test_cut_graph_applies_motion_before_cut_and_after_keeps_zoom(self):
        moving = replace(self.moving(), zoom=Zoom(True, 1.5))
        cuts = CutPlan((CutRange(3, 6),))
        cmd = build_export_command('ffmpeg', self.media, self.trim, 'out.mp4', moving, cuts=cuts)
        graph = cmd[cmd.index('-filter_complex')+1]
        self.assertEqual(graph.count("[0:v:0]crop=594:1056:x="), 2)
        self.assertIn('t+0.000000000', graph)
        self.assertIn('trim=start=1.000000000:end=3.000000000', graph)
        self.assertIn('trim=start=6.000000000:end=9.000000000', graph)
        self.assertLess(graph.index('crop=594:1056'), graph.index('trim=start=1.'))
        self.assertIn('concat=n=2:v=1:a=1', graph)
        self.assertIn('scale=1080:1920', graph)
        self.assertIn('[cutv]', graph)

    def test_preview_static_crop_matches_sample_at_source_time(self):
        moving = self.moving()
        preview = preview_command('ffmpeg', self.media, 5, 600, 380, moving,
                                  False, trim=self.trim)
        filt = preview[preview.index('-vf')+1]
        self.assertIn('crop=594:1056:664:12', filt)
        self.assertNotIn('clip(', filt)
        source = preview_command('ffmpeg', self.media, 5, 600, 380, moving, True)
        self.assertNotIn('crop=', ' '.join(source))

    def test_no_keyframes_preserves_existing_static_crop_export(self):
        cmd = build_export_command('ffmpeg', self.media, self.trim, 'out.mp4', self.base)
        self.assertIn('crop=594:1056:662:12', cmd[cmd.index('-vf')+1])
        self.assertNotIn('clip(', ' '.join(cmd))


if __name__ == '__main__':
    unittest.main()
