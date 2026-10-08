"""Real FFmpeg checks for zoom, speed, fades, and the combined promo pipeline."""
from dataclasses import replace
import hashlib
import os
import subprocess
import unittest

from capture.ffmpeg_backend import validate_output
from editor.export_job import ExportJob
from editor.models import TrimRange
from editor.polish import Fade, Zoom
from editor.preview import preview_command
from editor.privacy import Privacy, Rect
from editor.text_overlay import TextOverlay, TextResources
from editor.transforms import Branding, EditOptions
from tests import test_editor_formats_integration as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS') == '1', 'Opt-in real FFmpeg integration')
class RealPolishTests(unittest.TestCase):
    setUp = fixtures.RealFormatTests.setUp
    source = fixtures.RealFormatTests.source
    rgb = fixtures.RealFormatTests.rgb

    def export_polished(self, media, edits, trim=TrimRange(.5, 2.5)):
        job = ExportJob(self.backend)
        job.start(media, trim, edits=edits)
        self.assertTrue(job.wait(45))
        events = list(job.events.queue)
        self.assertEqual(events[-1].kind, 'saved', events[-1].message)
        path = events[-1].path
        info = validate_output(self.probe, path, media.has_audio)
        video = next(stream for stream in info['streams'] if stream['codec_type'] == 'video')
        self.assertEqual((video['width'], video['height']), edits.output_size(media))
        self.assertEqual(any(stream['codec_type'] == 'audio' for stream in info['streams']), media.has_audio)
        self.assertAlmostEqual(float(info['format']['duration']), edits.output_duration(trim.duration), delta=.14)
        return path

    def test_speed_durations_audio_silence_and_fades(self):
        for audio in (True, False):
            media = self.source(audio)
            for speed in (.5, 1.5, 2.0):
                with self.subTest(audio=audio, speed=speed):
                    path = self.export_polished(media, EditOptions(speed=speed, fade=Fade(True, True)))
                    decoded = subprocess.run([self.ffmpeg, '-v', 'error', '-i', str(path), '-f', 'null', '-'],
                                             capture_output=True, timeout=30)
                    self.assertEqual(decoded.returncode, 0, decoded.stderr)

    def test_zoom_preview_agrees_with_export_after_shifted_crop(self):
        media = self.source(False)
        edits = EditOptions(zoom=Zoom(True, 2.0, .8, .35)).with_format(media, '9:16 Vertical')
        edits = replace(edits, crop=edits.crop.moved(media, 100, 20))
        path = self.export_polished(media, edits)
        width, height = edits.output_size(media)

        export_frame = subprocess.run(
            [self.ffmpeg, '-v', 'error', '-ss', '.5', '-i', str(path), '-frames:v', '1',
             '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
            capture_output=True, timeout=15)
        self.assertEqual(export_frame.returncode, 0, export_frame.stderr)

        with TextResources(edits.text) as resources:
            cmd = preview_command(self.ffmpeg, media, 1.0, width, height, edits, False, resources)
        cmd[cmd.index('ppm')] = 'rawvideo'
        cmd[cmd.index('image2pipe')] = 'rawvideo'
        cmd[-1:-1] = ['-pix_fmt', 'rgb24']
        preview = subprocess.run(cmd, capture_output=True, timeout=15)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(len(preview.stdout), width*height*3)
        self.assertEqual(len(export_frame.stdout), len(preview.stdout))
        mean_error = sum(abs(a-b) for a, b in zip(export_frame.stdout, preview.stdout)) / len(preview.stdout)
        self.assertLess(mean_error, 18)

    def test_maximum_combined_export_preserves_source(self):
        media = self.source(True)
        digest = hashlib.sha256(media.path.read_bytes()).digest()
        edits = EditOptions(
            text=TextOverlay(True, 'PULSE DEMO'),
            branding=Branding(True, 'Bottom right', 'Medium'),
            privacy=Privacy('Pixelate', Rect(230, 100, 100, 100)),
            zoom=Zoom(True, 1.5, .55, .45),
            speed=1.5,
            fade=Fade(True, True),
        ).with_format(media, '9:16 Vertical')
        edits = replace(edits, crop=edits.crop.moved(media, 20, 0))
        path = self.export_polished(media, edits, TrimRange(.4, 3.4))
        self.assertTrue(path.is_file())
        self.assertEqual(hashlib.sha256(media.path.read_bytes()).digest(), digest)
        self.assertFalse(list(self.folder.glob('*.partial.mp4')))
        self.assertFalse(list(self.folder.glob('*.lock')))


if __name__ == '__main__':
    unittest.main()
