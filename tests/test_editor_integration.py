"""Opt-in real FFmpeg checks: set PULSE_RUN_FFMPEG_TESTS=1 before unittest."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from capture.ffmpeg_backend import Backend, run, validate_output
from editor.media import probe_media
from editor.models import TrimRange
from editor.export_job import ExportJob
from editor.preview import preview_command


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS') == '1', 'Opt-in real FFmpeg integration')
class RealEditorTests(unittest.TestCase):
    def test_audio_and_silent_trim_decode_and_preserve_source(self):
        ffmpeg, probe = shutil.which('ffmpeg'), shutil.which('ffprobe')
        self.assertTrue(ffmpeg and probe, 'Install FFmpeg and FFprobe for integration checks')
        with TemporaryDirectory() as folder:
            for audio in (False, True):
                with self.subTest(audio=audio):
                    source = Path(folder) / f'clip with spaces {audio}.mp4'
                    command = [ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=30']
                    if audio:
                        command += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-c:a', 'aac']
                    command += ['-t', '4', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)]
                    made = run(command, timeout=30)
                    self.assertEqual(made.returncode, 0, made.stderr)
                    digest = hashlib.sha256(source.read_bytes()).digest()
                    media = probe_media(probe, source)
                    self.assertEqual(media.has_audio, audio)
                    job = ExportJob(Backend(ffmpeg, probe, True))
                    job.start(media, TrimRange(.75, 2.75))
                    self.assertTrue(job.wait(30))
                    events = []
                    while not job.events.empty():
                        events.append(job.events.get())
                    result = events[-1]
                    self.assertEqual(result.kind, 'saved', result.message)
                    info = validate_output(probe, result.path, audio)
                    self.assertAlmostEqual(float(info['format']['duration']), 2, delta=.1)
                    decoded = run([ffmpeg, '-v', 'error', '-i', str(result.path), '-f', 'null', '-'], 30)
                    self.assertEqual(decoded.returncode, 0, decoded.stderr)
                    self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), digest)
                    frame = subprocess.run(preview_command(ffmpeg, media, 1, 320, 180), capture_output=True, timeout=15)
                    self.assertEqual(frame.returncode, 0, frame.stderr)
                    self.assertTrue(frame.stdout.startswith(b'P6'))
