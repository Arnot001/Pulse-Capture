"""Real format/branding/cancellation checks; opt in with PULSE_RUN_FFMPEG_TESTS=1."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import threading
import unittest
from capture.ffmpeg_backend import Backend, run, validate_output
from editor.export_job import ExportJob
from editor.media import probe_media
from editor.models import TrimRange
from editor.preview import preview_command
from editor.transforms import Branding, EditOptions, FORMATS, CORNERS, SIZES, watermark_geometry


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS') == '1', 'Opt-in real FFmpeg integration')
class RealFormatTests(unittest.TestCase):
    def setUp(self):
        self.ffmpeg, self.probe = shutil.which('ffmpeg'), shutil.which('ffprobe')
        self.assertTrue(self.ffmpeg and self.probe)
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.backend = Backend(self.ffmpeg, self.probe, True)

    def source(self, audio):
        path = self.folder / f'source {audio}.mp4'
        cmd = [self.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x480:rate=30']
        if audio:
            cmd += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-c:a', 'aac']
        cmd += ['-t', '4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)]
        result = run(cmd, 30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return probe_media(self.probe, path)

    def export(self, media, edits):
        job = ExportJob(self.backend)
        job.start(media, TrimRange(.5, 2.5), edits=edits)
        self.assertTrue(job.wait(30))
        events = list(job.events.queue)
        self.assertEqual(events[-1].kind, 'saved', events[-1].message)
        self.assertTrue(any(e.kind == 'progress' for e in events))
        path = events[-1].path
        info = validate_output(self.probe, path, media.has_audio)
        video = next(s for s in info['streams'] if s['codec_type'] == 'video')
        self.assertEqual((video['width'], video['height']), edits.output_size(media))
        self.assertEqual(any(s['codec_type'] == 'audio' for s in info['streams']), media.has_audio)
        self.assertAlmostEqual(float(info['format']['duration']), 2, delta=.1)
        decoded = run([self.ffmpeg, '-v', 'error', '-i', str(path), '-f', 'null', '-'], 30)
        self.assertEqual(decoded.returncode, 0, decoded.stderr)
        return path

    def rgb(self, path):
        result = subprocess.run([self.ffmpeg, '-v', 'error', '-i', str(path), '-frames:v', '1',
                                 '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'], capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_all_formats_audio_and_silence_and_rendered_previews(self):
        for audio in (False, True):
            media = self.source(audio)
            digest = hashlib.sha256(media.path.read_bytes()).digest()
            for preset in FORMATS:
                with self.subTest(audio=audio, preset=preset):
                    edits = EditOptions().with_format(media, preset)
                    if edits.crop:
                        edits = replace(edits, crop=edits.crop.moved(media, 10000, 10000))
                    self.export(media, edits)
                    preview = subprocess.run(preview_command(self.ffmpeg, media, 1, 320, 240, edits, False),
                                             capture_output=True, timeout=15)
                    self.assertEqual(preview.returncode, 0, preview.stderr)
                    self.assertTrue(preview.stdout.startswith(b'P6'))
            self.assertEqual(hashlib.sha256(media.path.read_bytes()).digest(), digest)
            self.assertFalse(list(self.folder.glob('*.partial.mp4')))
            self.assertFalse(list(self.folder.glob('*.lock')))

    def test_real_watermark_each_corner_and_size(self):
        media = self.source(True)
        base = EditOptions().with_format(media, '1:1 Square')
        clean = self.rgb(self.export(media, base))
        width, height = base.output_size(media)
        for corner in CORNERS:
            for size in SIZES:
                with self.subTest(corner=corner, size=size):
                    edits = replace(base, branding=Branding(True, corner, size))
                    branded = self.rgb(self.export(media, edits))
                    x, y, edge = watermark_geometry(width, height, edits.branding)
                    indexes = [((row*width+col)*3+channel)
                               for row in range(y, y+edge) for col in range(x, x+edge) for channel in range(3)]
                    # The actual output pixels must contain the logo in the chosen corner.
                    self.assertGreater(sum(abs(branded[i]-clean[i]) for i in indexes)/len(indexes), 8)
        silent = self.source(False)
        self.export(silent, EditOptions(branding=Branding(True)).with_format(silent, '9:16 Vertical'))
        preview = subprocess.run(preview_command(self.ffmpeg, media, 1, 320, 240, edits, False),
                                 capture_output=True, timeout=15)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertTrue(preview.stdout.startswith(b'P6'))

    def test_cancel_actual_process_removes_only_its_export(self):
        media = self.source(True)
        digest = hashlib.sha256(media.path.read_bytes()).digest()
        started = threading.Event()
        children = []
        def slow_popen(command, **kwargs):
            command.insert(command.index('-i'), '-re')
            child = subprocess.Popen(command, **kwargs)
            children.append(child)
            started.set()
            return child
        job = ExportJob(self.backend, popen=slow_popen)
        edits = EditOptions(branding=Branding(True)).with_format(media, '9:16 Vertical')
        job.start(media, TrimRange(0, 4), edits=edits)
        self.assertTrue(started.wait(5))
        self.assertIsNone(children[0].poll())
        job.cancel()
        self.assertTrue(job.wait(10))
        self.assertEqual(list(job.events.queue)[-1].kind, 'cancelled')
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(list(self.folder.iterdir()), [media.path])
        self.assertEqual(hashlib.sha256(media.path.read_bytes()).digest(), digest)
