"""Real output-pixel, text safety, combined render, and cleanup checks."""
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import statistics
import subprocess
import threading
import unittest
from unittest.mock import patch
from capture.ffmpeg_backend import run
from editor.media import probe_media
from editor.models import TrimRange
from editor.transforms import EditOptions, Branding, FORMATS
from editor.privacy import Rect, Privacy, output_mask
from editor.text_overlay import TextOverlay, TextResources
from editor.export_job import ExportJob
from editor.preview import preview_command, Preview
from tests import test_editor_formats_integration as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS') == '1', 'Opt-in real FFmpeg integration')
class RealOverlayTests(unittest.TestCase):
    setUp = fixtures.RealFormatTests.setUp
    source = fixtures.RealFormatTests.source
    export = fixtures.RealFormatTests.export
    rgb = fixtures.RealFormatTests.rgb

    def test_requested_combination_matrix_audio_silence_and_source_preservation(self):
        text = TextOverlay(True, 'Café [OK]')
        mask = Rect(230, 100, 100, 100)
        for audio in (True, False):
            media = self.source(audio)
            digest = hashlib.sha256(media.path.read_bytes()).digest()
            cases = [EditOptions(text=text), EditOptions(privacy=Privacy('Blur', mask)),
                     EditOptions(privacy=Privacy('Pixelate', mask)),
                     EditOptions(privacy=Privacy('Blur', mask)).with_format(media, '16:9 Landscape'),
                     EditOptions(text=text, branding=Branding(True)).with_format(media, '9:16 Vertical'),
                     EditOptions(privacy=Privacy('Pixelate', mask)).with_format(media, '1:1 Square'),
                     EditOptions(text=text, privacy=Privacy('Blur', mask), branding=Branding(True)).with_format(media, '9:16 Vertical'),
                     EditOptions(text=text, privacy=Privacy('Pixelate', mask), branding=Branding(True)).with_format(media, '9:16 Vertical')]
            for index, edits in enumerate(cases):
                with self.subTest(audio=audio, case=index):
                    self.export(media, edits)
                    with TextResources(edits.text) as resources:
                        result = subprocess.run(preview_command(self.ffmpeg, media, 1, 320, 240, edits, False, resources),
                                                capture_output=True, timeout=15)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertTrue(result.stdout.startswith(b'P6'))
            self.assertEqual(hashlib.sha256(media.path.read_bytes()).digest(), digest)

    def test_exact_mask_placement_in_actual_pixels_for_all_crops(self):
        source = self.folder / 'checker.mp4'
        pattern = "nullsrc=s=640x480:r=30,geq=lum='if(mod(floor(X/4)+floor(Y/4),2),235,16)':cb=128:cr=128"
        result = run([self.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', pattern, '-t', '4',
                      '-c:v', 'libx264', '-crf', '10', '-pix_fmt', 'yuv420p', str(source)], 30)
        self.assertEqual(result.returncode, 0, result.stderr)
        media = probe_media(self.probe, source)
        mask = Rect(241, 151, 100, 90)  # Deliberately odd offsets exercise exact placement.
        for preset in FORMATS:
            base = EditOptions().with_format(media, preset)
            if base.crop:
                base = replace(base, crop=base.crop.moved(media, 140, 20))
            width, height = base.output_size(media)
            clean = self.rgb(self.export(media, base))
            for mode in ('Blur', 'Pixelate'):
                with self.subTest(preset=preset, mode=mode):
                    edits = replace(base, privacy=Privacy(mode, mask))
                    hidden = self.rgb(self.export(media, edits))
                    rect = output_mask(mask, media, base.crop)
                    indexes = [(y*width+x)*3 for y in range(rect.y+8, rect.bottom-8)
                               for x in range(rect.x+8, rect.right-8)]
                    before, after = [clean[i] for i in indexes], [hidden[i] for i in indexes]
                    self.assertGreater(statistics.pstdev(before), 80)
                    self.assertLess(statistics.pstdev(after), 35)
                    outside = [(y*width+x)*3 for y in range(25, 75) for x in range(15, 65)]
                    self.assertLess(sum(abs(clean[i]-hidden[i]) for i in outside)/len(outside), 8)
                    # Preview at native dimensions agrees with the encoded export (compression tolerance).
                    cmd = preview_command(self.ffmpeg, media, .5, width, height, edits, False)
                    cmd[cmd.index('ppm')] = 'rawvideo'
                    cmd[cmd.index('image2pipe')] = 'rawvideo'
                    cmd[-1:-1] = ['-pix_fmt', 'rgb24']
                    frame = subprocess.run(cmd, capture_output=True, timeout=15)
                    self.assertEqual(frame.returncode, 0, frame.stderr)
                    self.assertEqual(len(frame.stdout), len(hidden))
                    self.assertLess(sum(abs(frame.stdout[i]-hidden[i]) for i in indexes)/len(indexes), 8)

    def test_one_pixel_clipped_mask_and_fully_cropped_out_mask_export(self):
        media = self.source(False)
        base = EditOptions().with_format(media, '1:1 Square')
        for mode in ('Blur', 'Pixelate'):
            for rect in (Rect(base.crop.x-1, 100, 2, 30), Rect(0, 0, 20, 20)):
                with self.subTest(mode=mode, mask=rect):
                    self.export(media, replace(base, privacy=Privacy(mode, rect)))

    def test_literal_unicode_text_positions_and_special_resource_paths(self):
        media = self.source(False)
        unusual = self.folder / "O'Brien [text], files; café"
        unusual.mkdir()
        value = "Café's [100%] %{n}\nПривет & (OK): \\ $()"
        clean = self.rgb(self.export(media, EditOptions()))
        for position in ('Top', 'Centre', 'Bottom'):
            edits = EditOptions(text=TextOverlay(True, value, position=position))
            with patch('editor.export_job.TextResources', side_effect=lambda text: TextResources(text, directory=unusual)):
                path = self.export(media, edits)
            image = self.rgb(path)
            width, height = edits.output_size(media)
            bands = [(0, 150), (160, 320), (330, 480)]
            changes = [sum(abs(image[i]-clean[i]) for y in range(a, b)
                           for i in range((y*width+80)*3, (y*width+560)*3)) for a, b in bands]
            self.assertEqual(changes.index(max(changes)), ('Top', 'Centre', 'Bottom').index(position))
            self.assertGreater(max(changes), 10000)
            self.assertEqual(list(unusual.iterdir()), [])

    def test_cancellation_and_launch_failure_remove_text_resources(self):
        media = self.source(True)
        edits = EditOptions(text=TextOverlay(True, 'Private'), branding=Branding(True),
                            privacy=Privacy('Pixelate', Rect(230, 100, 100, 100))).with_format(media, '9:16 Vertical')
        resource_paths = []
        def resources(text):
            result = TextResources(text)
            resource_paths.append(result.path)
            return result
        started = threading.Event()
        children = []
        def slow_popen(command, **kwargs):
            command.insert(command.index('-i'), '-re')
            child = subprocess.Popen(command, **kwargs)
            children.append(child)
            started.set()
            return child
        with patch('editor.export_job.TextResources', side_effect=resources):
            job = ExportJob(self.backend, popen=slow_popen)
            job.start(media, TrimRange(0, 4), edits=edits)
            self.assertTrue(started.wait(5))
            job.cancel()
            self.assertTrue(job.wait(10))
            self.assertEqual(list(job.events.queue)[-1].kind, 'cancelled')
            self.assertIsNotNone(children[0].poll())
            self.assertTrue(all(not path.exists() for path in resource_paths))
            job = ExportJob(self.backend, popen=lambda *a, **k: (_ for _ in ()).throw(OSError('launch failed')))
            job.start(media, TrimRange(0, 2), edits=edits)
            self.assertTrue(job.wait(5))
            self.assertEqual(list(job.events.queue)[-1].kind, 'error')
            self.assertTrue(all(not path.exists() for path in resource_paths))
        self.assertEqual(list(self.folder.iterdir()), [media.path])
        with patch('editor.preview.TextResources', side_effect=resources):
            preview = Preview(self.ffmpeg, media)
            try:
                preview.request(1, 1, 320, 240, edits, False)
                frame = preview.frames.get(timeout=15)
                self.assertFalse(frame.error, frame.error)
            finally:
                preview.close()
                preview._thread.join(15)
        self.assertTrue(all(not path.exists() for path in resource_paths))
