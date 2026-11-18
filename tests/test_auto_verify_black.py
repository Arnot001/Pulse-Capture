"""Auto Edit black-scene policy: content warnings never suppress a valid MP4."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import Backend, run
from editor.auto_verify import verify_short


class StubBackend:
    ffmpeg = "ffmpeg"
    ffprobe = "ffprobe"


def fixture_info(*, width=1080, audio=True):
    streams = [dict(codec_type="video", width=width, height=1920,
                    codec_name="h264", start_time="0", duration="3.000")]
    if audio:
        streams.append(dict(codec_type="audio", codec_name="aac",
                            start_time="0", duration="3.000"))
    return dict(streams=streams, format=dict(duration="3.000"))


class AutoShortVerificationTests(unittest.TestCase):
    def check(self, *, black=b"", data=None, corrupt=False, expect_audio=True):
        commands = []
        info = fixture_info() if data is None else data

        def synthetic_run(command, cancel, timeout):
            commands.append(tuple(command))
            if command[0] == "ffprobe":
                return json.dumps(info).encode()
            if "-xerror" in command:
                if corrupt:
                    raise ValueError("FFmpeg decode failed: broken video packets.")
                return b""
            return black

        with patch("editor.auto_verify.run_local", side_effect=synthetic_run):
            if corrupt:
                with self.assertRaisesRegex(ValueError, "decode failed"):
                    verify_short(StubBackend(), "clip.mp4", 3, expect_audio, threading.Event())
                return commands
            return verify_short(StubBackend(), "clip.mp4", 3, expect_audio, threading.Event()), commands

    def test_intentional_dark_transition_reports_interval_without_rejecting_short(self):
        metadata = (b"frame:20 pts:100\nlavfi.black_start=1.200\n"
                    b"frame:30 pts:200\nlavfi.black_end=1.510\n")
        result, commands = self.check(black=metadata)
        self.assertTrue(result["full_decode"])
        self.assertTrue(result["sustained_black_frames"])
        self.assertEqual(result["black_intervals"], [(1.2, 1.51)])
        self.assertTrue(any("-xerror" in command for command in commands))
        self.assertTrue(any("-vf" in command for command in commands))

    def test_absent_black_reports_no_advisory(self):
        result, _ = self.check()
        self.assertFalse(result["sustained_black_frames"])
        self.assertEqual(result["black_intervals"], [])

    def test_black_at_end_uses_actual_duration_and_does_not_fail(self):
        result, _ = self.check(black=b"lavfi.black_start=2.650\n")
        self.assertEqual(result["black_intervals"], [(2.65, 3)])

    def test_corrupt_decode_still_fails(self):
        self.check(corrupt=True)

    def test_incorrect_format_or_audio_sync_still_fail(self):
        with self.assertRaisesRegex(ValueError, "1080"):
            self.check(data=fixture_info(width=720))
        info = fixture_info()
        info["streams"][1]["start_time"] = "1.000"
        with self.assertRaisesRegex(ValueError, "start times"):
            self.check(data=info)


@unittest.skipUnless(os.environ.get("PULSE_RUN_FFMPEG_TESTS") == "1",
                     "Opt-in real FFmpeg black transition acceptance")
class RealBlackTransitionTests(unittest.TestCase):
    def test_real_h264_black_cut_is_valid_but_flagged_for_review(self):
        with tempfile.TemporaryDirectory(prefix="pulse-black-short-") as folder:
            folder = Path(folder)
            ffmpeg = shutil.which("ffmpeg")
            ffprobe = shutil.which("ffprobe")
            self.assertTrue(ffmpeg and ffprobe, "FFmpeg and FFprobe required")
            backend = Backend(ffmpeg, ffprobe, True)
            output = folder / "black-cut.mp4"
            result = run([
                ffmpeg, "-v", "error", "-nostdin", "-y",
                "-f", "lavfi", "-i", "color=c=0x4060a0:s=1080x1920:r=30:d=0.5",
                "-f", "lavfi", "-i", "color=c=black:s=1080x1920:r=30:d=0.3",
                "-f", "lavfi", "-i", "color=c=0x4060a0:s=1080x1920:r=30:d=0.5",
                "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]",
                "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", str(output),
            ], 40)
            self.assertEqual(result.returncode, 0, result.stderr)
            info = json.loads(run([ffprobe, "-v", "error", "-show_format", "-of", "json", str(output)], 10).stdout)
            duration = float(info["format"]["duration"])
            verified = verify_short(backend, output, duration, False, threading.Event())
            self.assertTrue(verified["full_decode"])
            self.assertTrue(verified["black_intervals"])
            self.assertTrue(any(end - start >= .15 for start, end in verified["black_intervals"]))


if __name__ == "__main__":
    unittest.main()
