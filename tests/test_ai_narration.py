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


    def test_editor_preview_and_export_share_narration(self):
        from dataclasses import replace
        from editor.audio_preview import audio_preview_command
        from editor.ffmpeg_export import build_export_command
        from editor.cuts import CutPlan
        from editor.models import MediaInfo, TrimRange
        from editor.transforms import EditOptions
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"LOCALAPPDATA": tmp}):
            path = voice_file(tmp)
            media = MediaInfo(Path("fictional.mp4"), 12, 1920, 1080, 30, True)
            edits = replace(EditOptions(), narration=Narration(str(path), start=1.5))
            preview = audio_preview_command("ffmpeg", media, 0, TrimRange(0, 12), CutPlan(), edits)
            self.assertIn("narrationmix", preview[preview.index("-filter_complex") + 1])
            self.assertIn(str(path.resolve()).casefold(), [str(x).casefold() for x in preview])
            output = build_export_command("ffmpeg", media, TrimRange(0, 12),
                                          Path(tmp)/"export.mp4", edits)
            self.assertIn(str(path.resolve()).casefold(), [str(x).casefold() for x in output])
            self.assertIn("narrationmix", output[output.index("-filter_complex") + 1])
            self.assertIn("[narrationmix]", output)
            silent = MediaInfo(Path("silent.mp4"), 12, 1920, 1080, 30, False)
            output2 = build_export_command("ffmpeg", silent, TrimRange(0, 12),
                                           Path(tmp)/"export2.mp4", edits)
            self.assertIn(str(path.resolve()).casefold(), [str(x).casefold() for x in output2])
            self.assertNotIn("-an", output2)


if __name__ == "__main__":
    unittest.main()
