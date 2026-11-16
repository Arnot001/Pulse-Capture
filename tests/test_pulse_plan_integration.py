"""Real decoded picture/audio checks; PULSE_RUN_FFMPEG_TESTS=1."""
from array import array
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import Backend, run, validate_output, validate_audio_coverage
from editor.auto_analysis import AutoCancelled
from editor.auto_plan import editor_state
from editor.export_job import ExportJob
from editor.ffmpeg_export import build_plan_segment_command
from editor.media import probe_media
from editor.pulse_job import assemble_plan
from editor.pulse_plan import source_identity, starter_plan
from editor.text_overlay import TextOverlay, TextResources
from editor.preview import preview_command


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS') == '1', 'Opt-in real FFmpeg integration')
class PulseIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        cls.backend = Backend(shutil.which('ffmpeg'), shutil.which('ffprobe'), True)
        source = cls.folder/'pulse-fixture.mp4'
        result = run([str(cls.backend.ffmpeg), '-v', 'error', '-nostdin', '-n',
                      '-f', 'lavfi', '-i', 'testsrc2=s=640x360:r=30,drawbox=x=0:y=0:w=40:h=360:c=red:t=fill,'
                      'drawbox=x=600:y=0:w=40:h=360:c=blue:t=fill',
                      '-f', 'lavfi', '-i', r'aevalsrc=0.3*sin(2*PI*if(lt(t\,2)\,440\,if(lt(t\,4)\,880\,1320))*t):s=48000',
                      '-t', '6', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)], 30)
        if result.returncode:
            raise RuntimeError(result.stderr)
        cls.media = probe_media(cls.backend.ffprobe, source)
        cls.identity = source_identity(cls.media, threading.Event())

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def plan(self):
        plan = starter_plan(self.media, self.identity)
        plan['timeline'] = [dict(kind='title', text='SETUP', duration=.5, animation='fade'),
                            dict(kind='shot', start=2, end=3, role='reveal'),
                            dict(kind='shot', start=0, end=1, role='setup'),
                            dict(kind='shot', start=2, end=3, role='replay'),
                            dict(kind='freeze', source_time=2.5, duration=1),
                            dict(kind='title', text='POCKET MAGIC?', duration=.5, animation='pop')]
        plan['captions'] = [dict(start=.5, end=1.5, text='LOOK AT THIS', zone='top', basis='observation'),
                            dict(start=2.5, end=3.5, text='INFINITE POCKETS', zone='bottom', basis='joke')]
        plan['timeline'][1]['commentary'] = 'A magic pocket? Record this commentary later.'
        return plan

    def render(self, plan):
        return assemble_plan(self.backend, self.media, plan, self.folder/'reviews', threading.Event())

    def rgb(self, path, at):
        result = subprocess.run([str(self.backend.ffmpeg), '-v', 'error', '-ss', str(at), '-i', str(path),
                                 '-frames:v', '1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def audio(self, path, at):
        result = subprocess.run([str(self.backend.ffmpeg), '-v', 'error', '-ss', str(at), '-i', str(path),
                                 '-t', '0.2', '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', '-'],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = array('f')
        data.frombytes(result.stdout)
        return data

    def test_replay_titles_freeze_captions_source_protection_and_audio_sync(self):
        plan = self.plan()
        digest = hashlib.sha256(self.media.path.read_bytes()).digest()
        folder, assembled = self.render(plan)
        trim, cuts, edits = editor_state(plan, self.media, assembled_media=assembled)
        self.assertIn('SCRIPT ONLY', (folder/'voiceover-script.txt').read_text(encoding='utf-8'))
        job = ExportJob(self.backend)
        job.start(assembled, trim, folder, edits, cuts)
        self.assertTrue(job.wait(120))
        event = list(job.events.queue)[-1]
        self.assertEqual(event.kind, 'saved', event.message)
        info = validate_output(self.backend.ffprobe, event.path, True)
        validate_audio_coverage(info)
        self.assertAlmostEqual(float(info['format']['duration']), 5, delta=.07)
        for at, frequency in ((.8, 880), (1.8, 440), (2.8, 880)):
            samples = self.audio(event.path, at)
            hz = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))/.2
            self.assertAlmostEqual(hz, frequency, delta=15, msg=f'Wrong audio shot at {at}s')
        for at in (.1, 3.8, 4.7):
            self.assertLess(max(abs(x) for x in self.audio(event.path, at)), .01)
        first, second = self.rgb(event.path, 3.7), self.rgb(event.path, 4.1)
        self.assertLess(sum(abs(a-b) for a, b in zip(first, second))/len(first), 1)
        # Both outer source edges remain visible in the centred widescreen picture.
        frame = self.rgb(event.path, .9)
        for x, channel in ((10, 0), (1060, 2)):
            pixel = frame[(960*1080+x)*3:(960*1080+x)*3+3]
            self.assertGreater(pixel[channel], 180)
            self.assertGreater(pixel[channel]-pixel[1], 100)
        # Caption pixels are in reserved top/bottom zones, never burned into footage.
        clean = self.rgb(assembled.path, .9)
        def difference(a, b, y0, y1):
            return sum(abs(x-y) for x, y in zip(a[y0*3240:y1*3240], b[y0*3240:y1*3240]))
        self.assertGreater(difference(frame, clean, 200, 400), 100000)
        self.assertLess(difference(frame, clean, 0, 180), 1000)
        bottom = self.rgb(event.path, 2.9)
        clean_bottom = self.rgb(assembled.path, 2.9)
        self.assertGreater(difference(bottom, clean_bottom, 1350, 1550), 100000)
        with TextResources(edits.text) as resources:
            preview = subprocess.run(preview_command(self.backend.ffmpeg, assembled, .9, 360, 640,
                                      edits, False, resources, trim, cuts), capture_output=True, timeout=30)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertTrue(preview.stdout.startswith(b'P6'))
        self.assertEqual(hashlib.sha256(self.media.path.read_bytes()).digest(), digest)
        self.assertFalse(list(folder.glob('*.partial.mp4')))
        self.assertFalse(list(folder.glob('*.lock')))

    def test_dissolve_fade_black_speed_volume_and_punch_in(self):
        plan = self.plan()
        plan['captions'] = []
        plan['timeline'] = [dict(kind='shot', start=0, end=1, speed=.5, volume=.5),
                            dict(kind='shot', start=2, end=3, zoom=dict(factor=1.5, x=.8, y=.5),
                                 transition=dict(type='dissolve', duration=.2)),
                            dict(kind='shot', start=4, end=5, volume=0,
                                 transition=dict(type='fade_black', duration=.2))]
        _, assembled = self.render(plan)
        self.assertAlmostEqual(assembled.duration, 3.6, delta=.05)
        samples = self.audio(assembled.path, .7)
        frequency = sum(a <= 0 < b for a, b in zip(samples, samples[1:]))/.2
        self.assertAlmostEqual(frequency, 440, delta=15)
        self.assertLess(max(abs(x) for x in samples), .2)
        self.assertLess(max(abs(x) for x in self.audio(assembled.path, 3.2)), .01)
        # The fade-through-black reaches black at the requested transition midpoint.
        black = self.rgb(assembled.path, 2.7)
        self.assertLess(sum(black)/len(black), 3)

    def test_all_title_animations_render_literal_text(self):
        for animation in ('none', 'fade', 'slide', 'pop', 'typewriter'):
            item = dict(kind='title', text='%{n} [x]', duration=.5, font_size=48, animation=animation)
            output = self.folder/f'title-{animation}.mp4'
            with TextResources(TextOverlay(True, item['text'], position='Centre')) as resources:
                command = build_plan_segment_command(self.backend.ffmpeg, self.media, item, output,
                                                     'full_frame', resources)
                self.assertNotIn(item['text'], ' '.join(command))
                result = run(command, 60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertAlmostEqual(probe_media(self.backend.ffprobe, output).duration, .5, delta=.04)

    def test_failure_and_cancellation_leave_no_review_or_source_changes(self):
        root = self.folder/'cancelled'
        digest = hashlib.sha256(self.media.path.read_bytes()).digest()
        cancel = threading.Event()
        def progress(message):
            if message.startswith('Rendering'):
                cancel.set()
        with self.assertRaises(AutoCancelled):
            assemble_plan(self.backend, self.media, self.plan(), root, cancel, progress)
        self.assertEqual(list(root.iterdir()), [])
        with patch('editor.pulse_job.run_local', side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):
                assemble_plan(self.backend, self.media, self.plan(), root, threading.Event())
        self.assertEqual(list(root.iterdir()), [])
        self.assertEqual(hashlib.sha256(self.media.path.read_bytes()).digest(), digest)


if __name__ == '__main__':
    unittest.main()
