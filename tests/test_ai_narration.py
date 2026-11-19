"""Offline narration track tests: timing, limits and FFmpeg graph compilation."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

from editor.narration import Narration, add_narration


def voice_file(root, seconds=3):
    folder = Path(root) / "Pulse Capture" / "voiceovers"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "sample.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * (seconds * 24000))
    return path


class NarrationTests(unittest.TestCase):
    def test_only_saved_assets_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            path = voice_file(tmp)
            cue = Narration(str(path), start=1.25, volume=.8)
            self.assertEqual(cue.validate(10), 3)
            with self.assertRaises(ValueError):
                Narration(str(Path(tmp) / "outside.wav")).validate()
            with self.assertRaises(ValueError):
                Narration(str(path), start=10).validate(10)
            with self.assertRaises(ValueError):
                Narration(str(path), volume=3).validate()

    def test_insert_and_duck_source(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            path = voice_file(tmp)
            args = ["-i", "original.mp4"]
            graph = []
            label = add_narration(args, graph, "source", Narration(str(path), 2, 1, .3), 12)
            self.assertEqual(label, "narrationmix")
            self.assertEqual(args.count("-i"), 2)
            self.assertIn("adelay=96000S", ";".join(graph))
            self.assertIn("0.3", ";".join(graph))
            self.assertIn("amix=inputs=2", ";".join(graph))

    def test_seeking_mid_voice_uses_output_clock(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            path = voice_file(tmp, 5)
            args, graph = ["-i", "original.mp4"], []
            label = add_narration(args, graph, None, Narration(str(path), start=2), 3, offset=4)
            self.assertEqual(label, "narrationmix")
            self.assertIn("atrim=start=2.000000000:end=5.000000000", ";".join(graph))
            self.assertIn("anullsrc", ";".join(graph))
            self.assertEqual(
                add_narration([], [], None, Narration(str(path), start=2), 3, offset=9), None)


if __name__ == "__main__":
    unittest.main()
