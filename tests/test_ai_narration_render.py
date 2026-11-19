"""Real FFmpeg voiceover export smoke test, using synthetic local media only.

No OpenAI requests, no downloaded files, and no third-party Python packages.
"""
from dataclasses import replace
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from editor.cuts import CutPlan, CutRange
from editor.ffmpeg_export import build_export_command
from editor.models import MediaInfo, TrimRange
from editor.narration import Narration
from editor.transforms import EditOptions

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def make_wav(path, freq, seconds, amplitude=9000):
    rate = 24000
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        samples = (round(amplitude * math.sin(2 * math.pi * freq * n / rate))
                   for n in range(round(rate * seconds)))
        f.writeframes(b"".join(struct.pack("<h", s) for s in samples))


def execute(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=100)
    if result.returncode:
        raise AssertionError("FFmpeg failed: " + result.stderr[-3500:])
    return result


@unittest.skipUnless(FFMPEG and FFPROBE, "FFmpeg/FFprobe not installed")
class NarrationRenderTests(unittest.TestCase):
    def test_actual_mp4_audio_and_silent_sources(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"LOCALAPPDATA": folder}):
            root = Path(folder)
            lib = root / "Pulse Capture" / "voiceovers"
            lib.mkdir(parents=True)
            narration = lib / "demo.wav"
            make_wav(narration, 880, 1.6)
            self.assertTrue(narration.is_file())
            for with_audio in (False, True):
                with self.subTest(source_audio=with_audio):
                    source = root / ("audible.mp4" if with_audio else "silent.mp4")
                    args = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                            "-f", "lavfi", "-i", "testsrc2=s=320x180:r=15:d=4"]
                    if with_audio:
                        args += ["-f", "lavfi", "-i", "sine=frequency=220:duration=4"]
                    args += ["-t", "4", "-c:v", "libx264", "-threads", "2", "-pix_fmt", "yuv420p"]
                    if with_audio:
                        args += ["-c:a", "aac"]
                    args += ["-y", str(source)]
                    execute(args)
                    media = MediaInfo(source, 4, 320, 180, 15, with_audio)
                    cue = Narration(str(narration), start=1.0, background_gain=.3)
                    edits = replace(EditOptions(), narration=cue)
                    output = root / ("voiced-audio.mp4" if with_audio else "voiced-silent.mp4")
                    command = build_export_command(FFMPEG, media, TrimRange(0, 4), output, edits)
                    execute(command)
                    info = execute([FFPROBE, "-v", "error", "-show_entries",
                                    "stream=codec_type:format=duration", "-of", "json", str(output)]).stdout
                    import json
                    parsed = json.loads(info)
                    self.assertEqual({s["codec_type"] for s in parsed["streams"]}, {"video", "audio"})
                    self.assertAlmostEqual(float(parsed["format"]["duration"]), 4, delta=.25)
                    decoded = subprocess.run(
                        [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(output),
                         "-map", "0:a:0", "-ar", "8000", "-ac", "1",
                         "-f", "s16le", "pipe:1"],
                        capture_output=True, timeout=60)
                    self.assertEqual(decoded.returncode, 0, decoded.stderr[-1000:])
                    pcm = decoded.stdout
                    self.assertGreater(len(pcm), 4 * 8000 * 2 - 2000)
                    def energy(at):
                        start = int(at * 8000) * 2
                        segment = pcm[start:start + 2000]
                        values = struct.unpack("<" + "h" * (len(segment) // 2), segment)
                        return sum(x*x for x in values) / max(1, len(values))
                    self.assertGreater(energy(1.25), energy(.3) * 2.0 if not with_audio else 200.0)


if __name__ == "__main__":
    unittest.main()
