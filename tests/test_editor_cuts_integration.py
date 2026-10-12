"""Real FFmpeg checks for multiple removed sections and the full edit pipeline."""
from dataclasses import replace
import hashlib
import os
import subprocess
import unittest

from capture.ffmpeg_backend import validate_output
from editor.cuts import CutPlan, CutRange
from editor.export_job import ExportJob
from editor.models import TrimRange
from editor.polish import Fade, Zoom
from editor.preview import preview_command
from editor.privacy import Privacy, Rect
from editor.text_overlay import TextOverlay, TextResources
from editor.transforms import Branding, EditOptions
from tests import test_editor_formats_integration as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS') == '1', 'Opt-in real FFmpeg integration')
class RealCutTests(unittest.TestCase):
    setUp = fixtures.RealFormatTests.setUp
    source = fixtures.RealFormatTests.source

    def export_cut(self, media, trim, cuts, edits=EditOptions()):
        job = ExportJob(self.backend)
        job.start(media, trim, edits=edits, cuts=cuts)
        self.assertTrue(job.wait(45))
        events = list(job.events.queue)
        self.assertEqual(events[-1].kind, 'saved', events[-1].message)
        path = events[-1].path
        info = validate_output(self.probe, path, media.has_audio)
        expected = edits.output_duration(cuts.kept_duration(trim))
        self.assertAlmostEqual(float(info['format']['duration']), expected, delta=.16)
        self.assertEqual(
            any(stream['codec_type'] == 'audio' for stream in info['streams']),
            media.has_audio,
        )
        decoded = subprocess.run(
            [self.ffmpeg, '-v', 'error', '-i', str(path), '-f', 'null', '-'],
            capture_output=True, timeout=30,
        )
        self.assertEqual(decoded.returncode, 0, decoded.stderr)
        return path

    def test_multiple_cuts_export_audio_and_silence(self):
        trim = TrimRange(.25, 3.75)
        cuts = CutPlan((CutRange(.75, 1.25), CutRange(2.0, 2.5)))
        for audio in (False, True):
            with self.subTest(audio=audio):
                media = self.source(audio)
                path = self.export_cut(media, trim, cuts)
                info = validate_output(self.probe, path, audio)
                self.assertAlmostEqual(float(info['format']['duration']), 2.5, delta=.16)

    def test_preview_matches_joined_output_after_removed_section(self):
        media = self.source(False)
        trim = TrimRange(.5, 3.5)
        cuts = CutPlan((CutRange(1.0, 1.5),))
        edits = EditOptions()
        path = self.export_cut(media, trim, cuts, edits)

        width, height = edits.output_size(media)
        export_frame = subprocess.run(
            [self.ffmpeg, '-v', 'error', '-ss', '1.0', '-i', str(path),
             '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
            capture_output=True, timeout=15,
        )
        self.assertEqual(export_frame.returncode, 0, export_frame.stderr)

        with TextResources(edits.text) as resources:
            cmd = preview_command(
                self.ffmpeg, media, 2.0, width, height, edits, False,
                resources, trim, cuts,
            )
        cmd[cmd.index('ppm')] = 'rawvideo'
        cmd[cmd.index('image2pipe')] = 'rawvideo'
        cmd[-1:-1] = ['-pix_fmt', 'rgb24']
        preview = subprocess.run(cmd, capture_output=True, timeout=15)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(len(export_frame.stdout), len(preview.stdout))
        mean_error = sum(
            abs(a-b) for a, b in zip(export_frame.stdout, preview.stdout)
        ) / len(preview.stdout)
        self.assertLess(mean_error, 18)

    def test_maximum_combined_cut_export_preserves_source(self):
        media = self.source(True)
        digest = hashlib.sha256(media.path.read_bytes()).digest()
        trim = TrimRange(.2, 3.8)
        cuts = CutPlan((CutRange(.8, 1.2), CutRange(2.2, 2.6)))
        edits = EditOptions(
            text=TextOverlay(True, 'PULSE CUT'),
            branding=Branding(True, 'Bottom right', 'Medium'),
            privacy=Privacy('Pixelate', Rect(230, 100, 50, 90)),
            zoom=Zoom(
                enabled=True, factor=1.5, focus_x=.58, focus_y=.42,
                mode='Zoom in', motion_speed='Full clip',
            ),
            speed=3.0,
            fade=Fade(True, True),
        ).with_format(media, '9:16 Vertical')
        edits = replace(edits, crop=edits.crop.moved(media, 20, 0))

        path = self.export_cut(media, trim, cuts, edits)
        info = validate_output(self.probe, path, True)
        video = next(stream for stream in info['streams'] if stream['codec_type'] == 'video')
        self.assertEqual((video['width'], video['height']), edits.output_size(media))
        self.assertAlmostEqual(
            float(info['format']['duration']),
            edits.output_duration(cuts.kept_duration(trim)),
            delta=.16,
        )
        self.assertTrue(path.is_file())
        self.assertEqual(hashlib.sha256(media.path.read_bytes()).digest(), digest)
        self.assertFalse(list(self.folder.glob('*.partial.mp4')))
        self.assertFalse(list(self.folder.glob('*.lock')))


if __name__ == '__main__':
    unittest.main()
