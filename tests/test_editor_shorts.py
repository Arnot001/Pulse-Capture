"""One-click YouTube Shorts framing stays compatible with existing editing tools."""
from dataclasses import replace
from pathlib import Path
import unittest

from editor.ffmpeg_export import build_export_command
from editor.models import MediaInfo, TrimRange
from editor.polish import Zoom
from editor.preview import preview_command
from editor.transforms import EditOptions, SHORTS_FORMAT, SHORTS_RESOLUTION, centered_crop


class ShortsTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('recording.mp4'), 10, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 3)

    def test_shorts_is_9_by_16_and_uses_existing_draggable_crop(self):
        edits = EditOptions().with_format(self.media, SHORTS_FORMAT)
        self.assertEqual(edits.crop, centered_crop(self.media, '9:16 Vertical'))
        self.assertEqual(edits.output_size(self.media), (594, 1056))
        self.assertEqual(edits.encoded_size(self.media), SHORTS_RESOLUTION)
        moved = replace(edits, crop=edits.crop.moved(self.media, 900, 0))
        self.assertEqual(moved.crop.x, 900)
        self.assertEqual(moved.encoded_size(self.media), (1080, 1920))

    def test_existing_portrait_needs_no_content_crop(self):
        portrait = replace(self.media, width=1080, height=1920)
        edits = EditOptions().with_format(portrait, SHORTS_FORMAT)
        self.assertEqual((edits.crop.x, edits.crop.y), (0, 0))
        self.assertEqual((edits.crop.width, edits.crop.height), (1080, 1920))
        self.assertEqual(edits.encoded_size(portrait), (1080, 1920))

    def test_simple_export_scales_after_crop_and_keeps_audio(self):
        edits = EditOptions().with_format(self.media, SHORTS_FORMAT)
        cmd = build_export_command('ffmpeg', self.media, self.trim, 'short.mp4', edits)
        filt = cmd[cmd.index('-vf') + 1]
        self.assertIn('crop=594:1056:662:12', filt)
        self.assertIn('scale=1080:1920:flags=lanczos,setsar=1', filt)
        self.assertLess(filt.index('crop='), filt.index('scale=1080:1920'))
        self.assertIn('0:a:0', cmd)
        self.assertIn('libx264', cmd)
        self.assertEqual(cmd[-1], 'short.mp4')

    def test_complex_zoom_and_preview_use_same_final_scaling(self):
        edits = EditOptions(zoom=Zoom(True, 1.5)).with_format(self.media, SHORTS_FORMAT)
        cmd = build_export_command('ffmpeg', self.media, self.trim, 'short.mp4', edits)
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertLess(graph.index('[zoomed]'), graph.index('scale=1080:1920'))
        self.assertIn('[shorts]null[v]', graph)
        preview = preview_command('ffmpeg', self.media, 1, 640, 360, edits,
                                  False, trim=self.trim)
        rendered = preview[preview.index('-filter_complex') + 1]
        self.assertIn('scale=1080:1920:flags=lanczos,setsar=1', rendered)
        source = preview_command('ffmpeg', self.media, 1, 640, 360, edits, True)
        self.assertNotIn('scale=1080:1920', ' '.join(source))

    def test_other_formats_keep_source_sized_exports(self):
        for preset in ('Original', '16:9 Landscape', '9:16 Vertical', '1:1 Square'):
            with self.subTest(preset=preset):
                edits = EditOptions().with_format(self.media, preset)
                self.assertEqual(edits.encoded_size(self.media), edits.output_size(self.media))
                cmd = build_export_command('ffmpeg', self.media, self.trim, 'other.mp4', edits)
                self.assertNotIn('scale=1080:1920', ' '.join(cmd))


if __name__ == '__main__':
    unittest.main()
