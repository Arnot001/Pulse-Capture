from dataclasses import replace
from pathlib import Path
import unittest

from editor.ffmpeg_export import build_export_command
from editor.models import MediaInfo, TrimRange
from editor.polish import Fade, Zoom, fade_seconds, output_duration, zoom_geometry
from editor.privacy import Privacy, Rect
from editor.text_overlay import TextOverlay, TextResources
from editor.transforms import Branding, EditOptions


class PolishGeometryTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 10, 1920, 1080, 30, True)

    def test_zoom_center_edges_and_presets(self):
        self.assertEqual(zoom_geometry(self.media, None, Zoom(True, 2.0)),
                         (480, 270, 960, 540, 1920, 1080))
        self.assertEqual(zoom_geometry(self.media, None, Zoom(True, 2.0, 0, 0)),
                         (0, 0, 960, 540, 1920, 1080))
        self.assertEqual(zoom_geometry(self.media, None, Zoom(True, 2.0, 1, 1)),
                         (960, 540, 960, 540, 1920, 1080))
        vertical = EditOptions().with_format(self.media, '9:16 Vertical')
        self.assertEqual(zoom_geometry(self.media, vertical.crop, Zoom(True, 1.5)),
                         (100, 176, 396, 704, 594, 1056))

    def test_zoom_clamps_focus_after_shifted_crop(self):
        edits = EditOptions().with_format(self.media, '9:16 Vertical')
        crop = edits.crop.moved(self.media, 900, 20)
        x, y, width, height, out_w, out_h = zoom_geometry(
            self.media, crop, Zoom(True, 2.0, 0.05, 0.95))
        self.assertEqual((x, y), (0, out_h-height))
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)

    def test_odd_dimensions_stay_encoder_safe(self):
        media = replace(self.media, width=1365, height=767)
        for factor in (1.25, 1.5, 2.0):
            geometry = zoom_geometry(media, None, Zoom(True, factor))
            self.assertTrue(all(value % 2 == 0 for value in geometry[:4]))
            self.assertTrue(all(value % 2 == 0 for value in geometry[4:]))

    def test_invalid_zoom_speed_and_duration(self):
        for zoom in (Zoom(True, 3), Zoom(True, 1.5, -0.1, .5), Zoom(True, 1.5, .5, 1.1)):
            with self.subTest(zoom=zoom), self.assertRaises(ValueError):
                zoom.validate()
        for speed in (0, .75, 3):
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                EditOptions(speed=speed).validate(self.media)
        self.assertEqual(output_duration(4, .5), 8)
        self.assertEqual(output_duration(4, 2), 2)
        self.assertEqual(fade_seconds(.4), .2)
        self.assertEqual(fade_seconds(5), .5)


class PolishCommandTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 10, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 3)

    def command(self, edits, media=None):
        media = media or self.media
        with TextResources(edits.text) as resources:
            return build_export_command('ffmpeg', media, self.trim, 'edited.mp4',
                                        edits, text_resources=resources)

    def test_zoom_is_after_privacy_before_text_and_brand(self):
        edits = EditOptions(
            zoom=Zoom(True, 1.5),
            privacy=Privacy('Blur', Rect(800, 300, 120, 100)),
            text=TextOverlay(True, 'Focus'),
            branding=Branding(True),
        )
        graph = self.command(edits)[self.command(edits).index('-filter_complex')+1]
        for first, second in (('gblur=', 'scale=1920:1080:flags=lanczos'),
                              ('flags=lanczos', 'drawtext='),
                              ('drawtext=', 'overlay=')):
            self.assertLess(graph.index(first), graph.index(second))

    def test_speed_adjusts_video_audio_and_expected_duration(self):
        for speed, expected in ((.5, 4), (1, 2), (1.5, 2/1.5), (2, 1)):
            edits = EditOptions(speed=speed)
            cmd = self.command(edits)
            self.assertAlmostEqual(edits.output_duration(self.trim.duration), expected)
            if speed == 1:
                self.assertNotIn('-af', cmd)
                self.assertNotIn('setpts=', ' '.join(cmd))
            else:
                self.assertIn(f'atempo={speed:g}', cmd[cmd.index('-af')+1])
                self.assertIn(f'setpts=PTS/{speed:g}', cmd[cmd.index('-filter_complex')+1])
            self.assertLess(cmd.index('-t'), cmd.index('-i'))
            self.assertEqual(cmd[cmd.index('-t')+1], '2.000000')

    def test_fades_follow_speed_and_audio(self):
        edits = EditOptions(speed=2.0, fade=Fade(True, True))
        cmd = self.command(edits)
        graph = cmd[cmd.index('-filter_complex')+1]
        self.assertLess(graph.index('setpts=PTS/2'), graph.index('fade=t=in'))
        self.assertIn('fade=t=out:st=0.500000:d=0.500000', graph)
        audio = cmd[cmd.index('-af')+1]
        self.assertIn('atempo=2', audio)
        self.assertIn('afade=t=in:st=0:d=0.500000', audio)
        self.assertIn('afade=t=out:st=0.500000:d=0.500000', audio)

    def test_silent_speed_and_fades_stay_silent(self):
        media = replace(self.media, has_audio=False)
        cmd = self.command(EditOptions(speed=.5, fade=Fade(True, True)), media)
        self.assertIn('-an', cmd)
        self.assertNotIn('-af', cmd)
        self.assertNotIn('0:a:0', cmd)

    def test_maximum_filter_order(self):
        edits = EditOptions(
            text=TextOverlay(True, 'Promo'),
            branding=Branding(True),
            privacy=Privacy('Pixelate', Rect(800, 300, 120, 100)),
            zoom=Zoom(True, 1.5),
            speed=1.5,
            fade=Fade(True, True),
        ).with_format(self.media, '9:16 Vertical')
        cmd = self.command(edits)
        graph = cmd[cmd.index('-filter_complex')+1]
        order = ['crop=594', 'pad=', 'flags=neighbor', 'scale=594:1056:flags=lanczos',
                 'drawtext=', 'overlay=', 'setpts=PTS/1.5', 'fade=t=in', 'fade=t=out']
        indexes = [graph.index(value) for value in order]
        self.assertEqual(indexes, sorted(indexes))


if __name__ == '__main__':
    unittest.main()
