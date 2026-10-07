import unittest
from capture.ffmpeg_backend import build_command
from capture.models import CaptureOptions, Region


class CommandTests(unittest.TestCase):
    def command(self, **kw):
        return build_command('C:/Tools/ffmpeg.exe', CaptureOptions(**kw), 'C:/My Videos/test.partial.mp4')

    def test_full_screen_and_no_overwrite(self):
        c = self.command()
        self.assertEqual(c[c.index('-i') + 1], 'desktop')
        self.assertIn('-n', c)
        self.assertNotIn('-y', c)
        self.assertIn('-an', c)
        self.assertEqual(c[-1], 'C:/My Videos/test.partial.mp4')

    def test_window_uses_handle_not_ambiguous_title(self):
        c = self.command(mode='window', hwnd=9876543210)
        self.assertIn('hwnd=9876543210', c)

    def test_negative_monitor_region_and_odd_dimensions(self):
        c = self.command(mode='region', region=Region(-1920, -50, 801, 603))
        self.assertEqual(c[c.index('-offset_x') + 1], '-1920')
        self.assertIn('801x603', c)
        self.assertIn('pad=ceil(iw/2)*2:ceil(ih/2)*2', c)

    def test_high_60(self):
        c = self.command(fps=60, quality='High')
        self.assertEqual(c[c.index('-crf') + 1], '18')
        self.assertEqual(c[c.index('-framerate') + 1], '60')

    def test_watermark_overlay_is_optional_and_uses_saved_position(self):
        c = self.command(watermark=True, watermark_position='Bottom right',
                         watermark_path='C:/Pulse/assets/branding/pulse.png')
        self.assertEqual(c.count('-i'), 2)
        self.assertIn('C:/Pulse/assets/branding/pulse.png', c)
        graph = c[c.index('-filter_complex') + 1]
        self.assertIn('scale=140:-1', graph)
        self.assertIn('colorchannelmixer=aa=0.82', graph)
        self.assertIn('overlay=W-w-24:H-h-24', graph)
        self.assertIn('[v]', c)

    def test_watermark_all_corner_positions(self):
        expected = {
            'Top left': 'overlay=24:24',
            'Top right': 'overlay=W-w-24:24',
            'Bottom left': 'overlay=24:H-h-24',
            'Bottom right': 'overlay=W-w-24:H-h-24',
        }
        for position, fragment in expected.items():
            with self.subTest(position=position):
                c = self.command(watermark=True, watermark_position=position,
                                 watermark_path='C:/Pulse/pulse.png')
                graph = c[c.index('-filter_complex') + 1]
                self.assertIn(fragment, graph)

    def test_mic_is_one_argument_without_shell_quotes(self):
        name = 'Microphone "USB" (Audio) & $(echo hi)'
        c = self.command(audio=(name,))
        self.assertIn('audio=' + name, c)
        self.assertIn('1:a:0', c)
        self.assertNotIn('-an', c)

    def test_two_devices_are_mixed_into_aac(self):
        c = self.command(audio=('mic', 'Stereo Mix'))
        self.assertEqual(c.count('-i'), 3)
        self.assertIn('-filter_complex', c)
        self.assertIn('[a]', c)
        self.assertIn('aac', c)

    def test_invalid_configuration_rejected(self):
        for kw in ({'mode': 'other'}, {'fps': 120}, {'quality': 'Ultra'},
                   {'mode': 'window'}, {'mode': 'region'},
                   {'mode': 'region', 'region': Region(0, 0, 0, 2)},
                   {'audio': ('same', 'same')},
                   {'watermark': True},
                   {'watermark_position': 'Center'}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.command(**kw)
