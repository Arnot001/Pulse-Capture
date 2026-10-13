"""Real FFmpeg checks for Quick Edit soundtrack mixing."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import subprocess
import unittest

from capture.ffmpeg_backend import run, validate_output
from editor.cuts import CutPlan, CutRange
from editor.export_job import ExportJob
from editor.models import TrimRange
from editor.music import IMPORT_LABEL, Music
from editor.polish import Fade, Zoom
from editor.privacy import Privacy, PrivacyMask, Rect
from editor.text_overlay import TextOverlay
from editor.transforms import Branding, EditOptions
from tests import test_editor_formats_integration as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS') == '1', 'Opt-in real FFmpeg integration')
class RealMusicTests(unittest.TestCase):
    setUp = fixtures.RealFormatTests.setUp
    source = fixtures.RealFormatTests.source

    def soundtrack(self, seconds=1.0, frequency=660):
        path = self.folder / f'music-{seconds}-{frequency}.wav'
        result = run([
            self.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
            f'sine=frequency={frequency}:sample_rate=48000',
            '-t', str(seconds), '-c:a', 'pcm_s16le', str(path),
        ], 20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return path

    def export_music(self, media, trim, cuts, edits):
        job = ExportJob(self.backend)
        job.start(media, trim, edits=edits, cuts=cuts)
        self.assertTrue(job.wait(45))
        events = list(job.events.queue)
        self.assertEqual(events[-1].kind, 'saved', events[-1].message)
        path = events[-1].path
        info = validate_output(self.probe, path, media.has_audio or edits.music.enabled)
        expected = edits.output_duration(cuts.kept_duration(trim))
        self.assertAlmostEqual(float(info['format']['duration']), expected, delta=.16)
        self.assertTrue(any(s['codec_type'] == 'audio' for s in info['streams']))
        decoded = subprocess.run(
            [self.ffmpeg, '-v', 'error', '-i', str(path), '-f', 'null', '-'],
            capture_output=True, timeout=30,
        )
        self.assertEqual(decoded.returncode, 0, decoded.stderr)
        return path, info

    def test_music_adds_audio_to_silent_and_mixes_with_source_audio(self):
        music_path = self.soundtrack(1.2)
        music = Music(
            True, IMPORT_LABEL, music_path, .20, .75,
            True, True, True,
        )
        for audio in (False, True):
            with self.subTest(source_audio=audio):
                media = self.source(audio)
                path, info = self.export_music(
                    media, TrimRange(.5, 3.5), CutPlan(), EditOptions(music=music)
                )
                self.assertTrue(path.is_file())
                self.assertEqual(
                    any(s['codec_type'] == 'audio' for s in info['streams']), True
                )

    def test_no_loop_short_music_is_padded_to_video_duration(self):
        media = self.source(False)
        music_path = self.soundtrack(.4, 550)
        music = Music(
            True, IMPORT_LABEL, music_path, .30, 1.0,
            False, False, False,
        )
        path, info = self.export_music(
            media, TrimRange(0, 4), CutPlan(), EditOptions(music=music)
        )
        audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
        self.assertAlmostEqual(float(audio['duration']), 4.0, delta=.16)
        self.assertTrue(path.is_file())

    def test_music_survives_cuts_speed_privacy_zoom_text_brand_and_fades(self):
        media = self.source(True)
        digest = hashlib.sha256(media.path.read_bytes()).digest()
        music_path = self.soundtrack(.7, 720)
        music = Music(
            True, IMPORT_LABEL, music_path, .15, .50,
            True, True, True,
        )
        trim = TrimRange(.2, 3.8)
        cuts = CutPlan((CutRange(.8, 1.2), CutRange(2.2, 2.6)))
        edits = EditOptions(
            text=TextOverlay(True, 'PULSE MUSIC'),
            branding=Branding(True, 'Bottom right', 'Medium'),
            privacy=Privacy((PrivacyMask('Blur', Rect(230, 100, 50, 90), 0, media.duration),)),
            music=music,
            zoom=Zoom(True, 1.5, .58, .42, 'Zoom in', 'Full clip'),
            speed=3.0,
            fade=Fade(True, True),
        ).with_format(media, '9:16 Vertical')
        edits = replace(edits, crop=edits.crop.moved(media, 20, 0))

        path, info = self.export_music(media, trim, cuts, edits)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
        self.assertEqual((video['width'], video['height']), edits.output_size(media))
        self.assertLess(abs(float(video['duration']) - float(audio['duration'])), .16)
        self.assertEqual(hashlib.sha256(media.path.read_bytes()).digest(), digest)
        self.assertFalse(list(self.folder.glob('*.partial.mp4')))
        self.assertFalse(list(self.folder.glob('*.lock')))
        self.assertTrue(path.is_file())


if __name__ == '__main__':
    unittest.main()
