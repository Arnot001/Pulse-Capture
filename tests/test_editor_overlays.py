from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from capture.ffmpeg_backend import Backend
from editor.models import MediaInfo, TrimRange
from editor.transforms import EditOptions, Branding, FORMATS
from editor.privacy import Rect, Privacy, output_mask, source_viewport, rectangle_from_points
from editor.text_overlay import TextOverlay, TextResources, text_geometry, filter_path, resolve_font
from editor.ffmpeg_export import build_export_command
from editor.preview import preview_command
from editor.export_job import ExportJob


class PrivacyGeometryTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 10, 1920, 1080, 30, True)

    def test_valid_modes_and_rectangles(self):
        for mode in ('Blur', 'Pixelate'):
            Privacy(mode, Rect(15, 21, 100, 80)).validate(self.media)

    def test_invalid_rectangles(self):
        for rect in (Rect(0, 0, 0, 10), Rect(0, 0, -10, 10), Rect(0, 0, 10, 0),
                     Rect(-1, 0, 10, 10), Rect(1919, 0, 10, 10), Rect(0, 1079, 10, 10),
                     Rect(0.5, 0, 10, 10), Rect(0, 0, 1, 10)):
            with self.subTest(rect=rect), self.assertRaises(ValueError):
                Privacy(mask=rect).validate(self.media)
        with self.assertRaises(ValueError):
            Privacy('unknown').validate(self.media)

    def test_drag_clamps_every_edge(self):
        bounds = Rect(50, 70, 300, 200)
        mask = Rect(80, 100, 100, 90)
        self.assertEqual(mask.moved(bounds, -500, -500), Rect(50, 70, 100, 90))
        self.assertEqual(mask.moved(bounds, 10000, 10000), Rect(250, 180, 100, 90))
        with self.assertRaises(ValueError):
            mask.moved(bounds, float('nan'), 10)

    def test_draw_resize_reverse_drag_and_zero_click(self):
        bounds = Rect(50, 70, 300, 200)
        self.assertEqual(rectangle_from_points(bounds, 400, 300, -100, -100), bounds)
        self.assertEqual(rectangle_from_points(bounds, 220, 240, 80, 100), Rect(80, 100, 140, 140))
        self.assertIsNone(rectangle_from_points(bounds, 100, 100, 100, 100))

    def test_source_anchor_mapping_after_every_preset(self):
        mask = Rect(720, 120, 100, 80)
        expected = {'Original': mask, '16:9 Landscape': mask,
                    '9:16 Vertical': Rect(58, 108, 100, 80), '1:1 Square': Rect(300, 120, 100, 80)}
        for preset in FORMATS:
            edits = EditOptions(privacy=Privacy(mask=mask)).with_format(self.media, preset)
            self.assertEqual(edits.privacy.mask, mask)
            self.assertEqual(output_mask(mask, self.media, edits.crop), expected[preset])

    def test_shifted_crop_uses_source_pixels_not_relative_percentage(self):
        edits = EditOptions().with_format(self.media, '9:16 Vertical')
        moved = edits.crop.moved(self.media, 700, 20)
        self.assertEqual(output_mask(Rect(720, 120, 100, 80), self.media, moved), Rect(20, 100, 100, 80))

    def test_partial_and_invisible_masks_clip_without_moving_source(self):
        crop = EditOptions().with_format(self.media, '1:1 Square').crop
        self.assertEqual(output_mask(Rect(400, 100, 100, 80), self.media, crop), Rect(0, 100, 80, 80))
        self.assertIsNone(output_mask(Rect(0, 0, 100, 100), self.media, crop))
        self.assertEqual(output_mask(Rect(419, 20, 2, 30), self.media, crop), Rect(0, 20, 1, 30))

    def test_viewport_round_trip_after_shifted_crop(self):
        edits = EditOptions().with_format(self.media, '9:16 Vertical')
        crop = edits.crop.moved(self.media, 700, 20)
        viewport = source_viewport(self.media, crop)
        mask = rectangle_from_points(viewport, viewport.x+12, viewport.y+18, viewport.x+112, viewport.y+98)
        self.assertEqual(output_mask(mask, self.media, crop), Rect(12, 18, 100, 80))


class TextTests(unittest.TestCase):
    def test_safe_unicode_and_symbols(self):
        for value in ("It's a demo: [hello], 100%", 'Café — Καλημέρα Привет', '文字 + ★ ©',
                      '$(whoami); & \"quotes\" \\ path', '%{localtime} / {braces}', 'Line one\nLine two'):
            TextOverlay(True, value).validate()

    def test_empty_invalid_and_limits(self):
        for text in (TextOverlay(True, ''), TextOverlay(True, '   '), TextOverlay(True, 'x'*161),
                     TextOverlay(True, 'a\nb\nc\nd'), TextOverlay(True, 'nul\x00here'),
                     TextOverlay(True, 'tab\there'), TextOverlay(True, 'text', 'huge'),
                     TextOverlay(True, 'text', position='unknown')):
            with self.subTest(text=text), self.assertRaises(ValueError):
                text.validate()
        TextOverlay(False, '').validate()

    def test_sizes_positions_and_long_text_fit(self):
        sizes = [text_geometry(1920, 1080, TextOverlay(True, 'Hello', s))[0]
                 for s in ('Small', 'Medium', 'Large')]
        self.assertEqual(sizes, sorted(set(sizes)))
        for position, y in [('Top', '43'), ('Centre', '(h-text_h)/2'), ('Bottom', 'h-text_h-43')]:
            self.assertEqual(text_geometry(1920, 1080, TextOverlay(True, 'Hello', position=position))[2], y)
        size, margin, _ = text_geometry(500, 800, TextOverlay(True, 'Text with a longer line'))
        self.assertLessEqual(size*23+2*margin, 500)

    def test_utf8_resources_are_exact_and_cleaned(self):
        text = TextOverlay(True, "Café's [100%]: %{n} — Привет")
        with TextResources(text) as resources:
            path = resources.path
            self.assertEqual(path.read_text(encoding='utf-8'), text.text)
            self.assertTrue(resources.font.is_file())
        self.assertFalse(path.exists())

    def test_disabled_needs_no_font_or_temp_file(self):
        with patch('editor.text_overlay.resolve_font', side_effect=AssertionError('font access')):
            with TextResources(TextOverlay()) as resources:
                self.assertIsNone(resources.path)

    def test_missing_system_font_is_a_clear_error(self):
        with patch('editor.text_overlay.Path.is_file', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Windows text font'):
                resolve_font()


class OverlayCommandTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source & name.mp4'), 10, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 3)

    def command(self, edits, media=None):
        with TextResources(edits.text) as resources:
            return build_export_command('ffmpeg', media or self.media, self.trim, 'edited copy.mp4',
                                        edits, text_resources=resources)

    def test_disabled_overlays_have_no_new_filters(self):
        cmd = self.command(EditOptions())
        self.assertNotIn('-filter_complex', cmd)
        self.assertNotIn('drawtext', ' '.join(cmd))
        self.assertEqual(cmd.count('-i'), 1)

    def test_text_is_never_in_command_or_expanded(self):
        value = "Café's [words]; $(whoami) %{n}"
        cmd = self.command(EditOptions(text=TextOverlay(True, value)))
        graph = cmd[cmd.index('-filter_complex')+1]
        self.assertNotIn(value, ' '.join(cmd))
        self.assertIn('textfile=', graph)
        self.assertIn('expansion=none', graph)
        self.assertIn('fontfile=', graph)
        self.assertEqual(cmd.count('-i'), 1)
        self.assertEqual(cmd[-1], 'edited copy.mp4')
        self.assertIn(str(self.media.path), cmd)

    def test_trim_crop_blur_and_pixelate(self):
        for mode, filter_name in [('Blur', 'gblur='), ('Pixelate', 'flags=neighbor')]:
            edits = EditOptions(privacy=Privacy(mode, Rect(720, 120, 100, 80))).with_format(self.media, '9:16 Vertical')
            cmd = self.command(edits)
            graph = cmd[cmd.index('-filter_complex')+1]
            self.assertIn('crop=100:80:58:108:exact=1', graph)
            self.assertIn(filter_name, graph)
            self.assertEqual(cmd.count('-i'), 1)
            self.assertEqual(cmd[cmd.index('-t')+1], '2.000000')

    def test_combined_order_and_audio(self):
        edits = EditOptions(text=TextOverlay(True, 'Hello'), branding=Branding(True),
                            privacy=Privacy('Pixelate', Rect(720, 120, 100, 80))).with_format(self.media, '9:16 Vertical')
        cmd = self.command(edits)
        graph = cmd[cmd.index('-filter_complex')+1]
        for first, second in [('crop=594', 'pad='), ('pad=', 'split'), ('flags=neighbor', 'drawtext='),
                              ('drawtext=', '[text][wm]overlay=')]:
            self.assertLess(graph.index(first), graph.index(second))
        self.assertIn('0:a:0', cmd)
        self.assertEqual(cmd.count('-i'), 2)
        self.assertIn('-n', cmd)
        self.assertNotIn('-y', cmd)
        silent = self.command(edits, replace(self.media, has_audio=False))
        self.assertIn('-an', silent)
        self.assertNotIn('0:a:0', silent)

    def test_crop_text_and_text_brand_combinations(self):
        for edits in (EditOptions(text=TextOverlay(True, 'Hello')).with_format(self.media, '1:1 Square'),
                      EditOptions(text=TextOverlay(True, 'Hello'), branding=Branding(True))):
            cmd = self.command(edits)
            self.assertIn('drawtext=', cmd[cmd.index('-filter_complex')+1])

    def test_preview_uses_identical_graph(self):
        edits = EditOptions(text=TextOverlay(True, 'Hello'), privacy=Privacy(mask=Rect(100, 100, 200, 200)))
        with TextResources(edits.text) as resources:
            cmd = build_export_command('ffmpeg', self.media, self.trim, 'out.mp4', edits, text_resources=resources)
            preview = preview_command('ffmpeg', self.media, 1, 640, 360, edits, False, resources)
            self.assertTrue(preview[preview.index('-filter_complex')+1].startswith(cmd[cmd.index('-filter_complex')+1]))

    def test_invalid_state_never_launches(self):
        for edits in (EditOptions(text=TextOverlay(True, '')), EditOptions(privacy=Privacy(mask=Rect(-1, 1, 20, 20)))):
            with self.subTest(edits=edits):
                launch = unittest.mock.Mock()
                job = ExportJob(Backend('ffmpeg', 'ffprobe', True), popen=launch)
                with self.assertRaises(ValueError):
                    job.start(self.media, self.trim, edits=edits)
                launch.assert_not_called()
                self.assertFalse(job.busy)
