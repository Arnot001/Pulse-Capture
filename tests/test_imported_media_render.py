"""Optional real FFmpeg smoke test: photo and B-roll must render into the MP4."""
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

from editor.ffmpeg_export import build_export_command
from editor.imported_media import MediaClip
from editor.media import probe_media
from editor.models import TrimRange
from editor.transforms import EditOptions


def _write_png(path, width=16, height=16, rgb=(0, 255, 0)):
    def chunk(name, data):
        return struct.pack('>I', len(data)) + name + data + struct.pack('>I', zlib.crc32(name + data))
    raw = b''.join(b'\x00' + bytes(rgb) * width for _ in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' +
                     chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
                     chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'FFmpeg + FFprobe are required for end-to-end media render')
class ImportedMediaRenderTests(unittest.TestCase):
    def test_real_photo_and_video_cutaway_render_without_losing_audio(self):
        ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
        with tempfile.TemporaryDirectory(prefix='pulse-media-render-') as tmp:
            root = Path(tmp)
            source, broll, photo, output = (root / name for name in
                                             ('source.mp4', 'broll.mp4', 'photo.png', 'result.mp4'))
            _write_png(photo)
            base = subprocess.run(
                [ffmpeg, '-hide_banner', '-v', 'error',
                 '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=24:d=4',
                 '-f', 'lavfi', '-i', 'sine=frequency=700:sample_rate=48000:duration=4',
                 '-c:v', 'mpeg4', '-q:v', '4', '-c:a', 'aac', '-shortest', '-y', str(source)],
                capture_output=True, timeout=35)
            self.assertEqual(base.returncode, 0, base.stderr.decode('utf-8', 'replace'))
            insert = subprocess.run(
                [ffmpeg, '-hide_banner', '-v', 'error',
                 '-f', 'lavfi', '-i', 'color=c=red:s=320x180:r=24:d=2',
                 '-c:v', 'mpeg4', '-q:v', '4', '-y', str(broll)],
                capture_output=True, timeout=35)
            self.assertEqual(insert.returncode, 0, insert.stderr.decode('utf-8', 'replace'))
            media = probe_media(ffprobe, source)
            broll_meta = probe_media(ffprobe, broll)
            edits = EditOptions(media_clips=(
                MediaClip(str(photo), 'photo', .5, 1.5, layout='Cutaway'),
                MediaClip(str(broll), 'video', 2., 3., 0., broll_meta.duration,
                          layout='Picture in picture', x=.1, y=1., scale=.5,
                          source_width=broll_meta.width, source_height=broll_meta.height),
            ))
            command = build_export_command(ffmpeg, media, TrimRange(0., media.duration), output, edits)
            rendered = subprocess.run(command, capture_output=True, timeout=75)
            self.assertEqual(rendered.returncode, 0, rendered.stderr.decode('utf-8', 'replace')[-2500:])
            self.assertTrue(output.is_file())
            result = probe_media(ffprobe, output)
            self.assertTrue(result.has_audio, 'Imported video must preserve original recording audio')
            self.assertAlmostEqual(result.duration, media.duration, delta=.15)
            def frame(at):
                result = subprocess.run(
                    [ffmpeg, '-v', 'error', '-ss', str(at), '-i', str(output), '-frames:v', '1',
                     '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
                    capture_output=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
                self.assertEqual(len(result.stdout), 320 * 180 * 3)
                return result.stdout
            def pixel(data, x, y):
                start = (y * 320 + x) * 3
                return tuple(data[start:start+3])
            photo_frame = frame(1.0)
            photo_colour = pixel(photo_frame, 160, 90)
            self.assertGreater(photo_colour[1], photo_colour[0] + 60)
            self.assertGreater(photo_colour[1], photo_colour[2] + 60)
            pip_frame = frame(2.5)
            pip_colour = pixel(pip_frame, 40, 130)
            self.assertGreater(pip_colour[0], pip_colour[1] + 60)
            self.assertGreater(pip_colour[0], pip_colour[2] + 60)
            background = pixel(pip_frame, 275, 45)
            self.assertGreater(background[2], background[0] + 60)


if __name__ == '__main__':
    unittest.main()
