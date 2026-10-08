from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch
from branding import watermark_path
from editor.models import MediaInfo, TrimRange
from editor.transforms import (Branding, Crop, EditOptions, FORMATS, CORNERS, SIZES,
                               centered_crop, watermark_geometry)
from editor.ffmpeg_export import build_export_command
from editor.preview import preview_command
from editor.export_job import ExportJob
from capture.ffmpeg_backend import Backend


class CropTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 10, 1920, 1080, 30, True)

    def test_centered_presets(self):
        for preset, expected in [('16:9 Landscape', Crop(0, 0, 1920, 1080)),
                                 ('9:16 Vertical', Crop(662, 12, 594, 1056)),
                                 ('1:1 Square', Crop(420, 0, 1080, 1080))]:
            with self.subTest(preset=preset):
                self.assertEqual(centered_crop(self.media, preset), expected)
                expected.validate(self.media)

    def test_portrait_to_landscape_and_odd_sources(self):
        for width, height in [(1080, 1920), (801, 601), (1365, 767), (33, 33)]:
            media = replace(self.media, width=width, height=height)
            for preset, ratio in FORMATS.items():
                edits = EditOptions().with_format(media, preset)
                out_w, out_h = edits.output_size(media)
                self.assertEqual(out_w % 2, 0)
                self.assertEqual(out_h % 2, 0)
                if ratio:
                    self.assertEqual(out_w * ratio[1], out_h * ratio[0])
                    self.assertLessEqual(out_w, width)
                    self.assertLessEqual(out_h, height)

    def test_original_restores_full_frame_but_preserves_branding(self):
        edits = EditOptions(branding=Branding(True)).with_format(self.media, '9:16 Vertical')
        original = edits.with_format(self.media, 'Original')
        self.assertIsNone(original.crop)
        self.assertTrue(original.branding.enabled)
        self.assertIsNone(centered_crop(self.media, 'Original'))
        self.assertEqual(original.output_size(self.media), (1920, 1080))

    def test_drag_clamps_all_edges_and_quantizes(self):
        crop = centered_crop(self.media, '9:16 Vertical')
        self.assertEqual(crop.moved(self.media, -100, -20), replace(crop, x=0, y=0))
        self.assertEqual(crop.moved(self.media, 10000, 10000), replace(crop, x=1326, y=24))
        self.assertEqual(crop.moved(self.media, 103.3, 11.2), replace(crop, x=104, y=12))
        with self.assertRaises(ValueError):
            crop.moved(self.media, float('nan'), 0)

    def test_invalid_states_rejected(self):
        for edits in (EditOptions('unknown'), EditOptions('1:1 Square'),
                      EditOptions(crop=Crop(0, 0, 100, 100)),
                      EditOptions('1:1 Square', Crop(-2, 0, 1080, 1080)),
                      EditOptions('1:1 Square', Crop(0, 0, 1081, 1080)),
                      EditOptions('1:1 Square', Crop(0, 0, 500, 500)),
                      EditOptions('1:1 Square', Crop(1000, 0, 1080, 1080)),
                      EditOptions('1:1 Square', Crop(0.0, 0, 1080, 1080)),
                      EditOptions(branding=Branding(True, 'middle')),
                      EditOptions(branding=Branding(True, size='Huge'))):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                edits.validate(self.media)
        with self.assertRaises(ValueError):
            centered_crop(replace(self.media, width=8, height=8), '16:9 Landscape')

    def test_trim_changes_do_not_change_crop(self):
        edits = EditOptions().with_format(self.media, '1:1 Square')
        moved = replace(edits, crop=edits.crop.moved(self.media, 80, 0))
        for trim in (TrimRange(0, 10), TrimRange(1, 2)):
            build_export_command('ffmpeg', self.media, trim, 'new.mp4', moved)
            self.assertEqual(moved.crop.x, 80)

    def test_invalid_state_rejected_before_worker_starts(self):
        job = ExportJob(Backend('ffmpeg', 'ffprobe', True))
        with self.assertRaises(ValueError):
            job.start(self.media, TrimRange(0, 2), edits=EditOptions('1:1 Square'))
        self.assertFalse(job.busy)


class BrandingCommandTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 10, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 3)

    def test_default_off_and_trim_crop_filter(self):
        edits = EditOptions().with_format(self.media, '1:1 Square')
        cmd = build_export_command('ffmpeg', self.media, self.trim, 'out.mp4', edits)
        self.assertFalse(edits.branding.enabled)
        self.assertEqual(cmd.count('-i'), 1)
        self.assertEqual(cmd[cmd.index('-vf')+1], 'crop=1080:1080:420:0,pad=ceil(iw/2)*2:ceil(ih/2)*2')
        self.assertIn('0:a:0', cmd)
        self.assertEqual(cmd[cmd.index('-t')+1], '2.000000')

    def test_all_corners_and_sizes_crop_before_brand(self):
        with TemporaryDirectory() as folder:
            asset = Path(folder) / 'Pulse & logo.png'
            asset.touch()
            for corner in CORNERS:
                sizes = []
                for size in SIZES:
                    edits = EditOptions(branding=Branding(True, corner, size)).with_format(self.media, '1:1 Square')
                    cmd = build_export_command('ffmpeg', self.media, self.trim, 'out.mp4', edits, asset)
                    graph = cmd[cmd.index('-filter_complex')+1]
                    x, y, edge = watermark_geometry(1080, 1080, edits.branding)
                    sizes.append(edge)
                    self.assertIn(f'overlay={x}:{y}:', graph)
                    self.assertIn(f'scale={edge}:{edge}', graph)
                    self.assertLess(graph.index('crop='), graph.index('pad='))
                    self.assertLess(graph.index('pad='), graph.index('overlay='))
                    self.assertIn(str(asset), cmd)
                    self.assertIn('0:a:0', cmd)
                    self.assertIn('[v]', cmd)
                    self.assertNotIn('-shortest', cmd)
                    self.assertIn('-n', cmd)
                    self.assertNotIn('-y', cmd)
                    self.assertGreaterEqual(x, 0)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(x+edge, 1080)
                    self.assertLessEqual(y+edge, 1080)
                self.assertEqual(sizes, sorted(set(sizes)))

    def test_corner_coordinates_and_size_presets(self):
        expected = {'Top left': (25, 25), 'Top right': (855, 25),
                    'Bottom left': (25, 855), 'Bottom right': (855, 855)}
        for corner, xy in expected.items():
            self.assertEqual(watermark_geometry(1000, 1000, Branding(True, corner)), (*xy, 120))
        self.assertEqual([watermark_geometry(1000, 1000, Branding(True, size=s))[2]
                          for s in SIZES], [120, 180, 250])

    def test_branded_silent_input_stays_silent(self):
        cmd = build_export_command('ffmpeg', replace(self.media, has_audio=False), self.trim,
                                   'out.mp4', EditOptions(branding=Branding(True)))
        self.assertIn('-an', cmd)
        self.assertNotIn('0:a:0', cmd)

    def test_missing_asset_clean_error_only_when_enabled(self):
        with self.assertRaisesRegex(ValueError, 'branding asset is missing'):
            build_export_command('ffmpeg', self.media, self.trim, 'out.mp4',
                                 EditOptions(branding=Branding(True)), 'missing.png')
        build_export_command('ffmpeg', self.media, self.trim, 'out.mp4', asset='missing.png')

    def test_preview_shares_export_filters_and_crop_view_is_source(self):
        edits = EditOptions(branding=Branding(True)).with_format(self.media, '9:16 Vertical')
        export = build_export_command('ffmpeg', self.media, self.trim, 'out.mp4', edits)
        preview = preview_command('ffmpeg', self.media, 1, 600, 400, edits, False)
        self.assertTrue(preview[preview.index('-filter_complex')+1].startswith(export[export.index('-filter_complex')+1]))
        source = preview_command('ffmpeg', self.media, 1, 600, 400, edits, True)
        self.assertNotIn('-filter_complex', source)
        self.assertEqual(source.count('-i'), 1)

    def test_packaged_branding_path(self):
        with patch.object(sys, '_MEIPASS', 'bundle', create=True):
            self.assertEqual(watermark_path(), Path('bundle/assets/branding/pulse.png'))
