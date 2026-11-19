"""Offline, zero-cost tests for GPT narration safeguards."""
import io
import json
from pathlib import Path
import tempfile
import unittest
import wave

from editor.ai_voiceover import SpeechRequest, generate, library_root


def fake_wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\0\0" * 2400)
    return output.getvalue()


class VoiceoverTests(unittest.TestCase):
    def test_payload_and_bounds(self):
        req = SpeechRequest("Where did that gun come from?", "marin", "Dry British")
        self.assertEqual(req.payload()["response_format"], "wav")
        self.assertIn("British", req.payload()["instructions"])
        for bad in ("", "x" * 701, "Hello\x00"):
            with self.assertRaises(ValueError):
                SpeechRequest(bad).validate()
        with self.assertRaises(ValueError):
            SpeechRequest("hello", "made-up-voice").validate()

    def test_requires_consent(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            with self.assertRaisesRegex(ValueError, "Confirm"):
                generate(SpeechRequest("hello"), root=tmp,
                         sender=lambda *x: calls.append(x))
            self.assertEqual(calls, [])
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_reuses_local_file_with_zero_new_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            req = SpeechRequest("Narration once")
            def sender(*args):
                calls.append(args)
                return fake_wav()
            first, was_cached = generate(req, root=tmp, approval=True,
                                         api_key="test-only", sender=sender)
            self.assertFalse(was_cached)
            self.assertTrue(first.is_file())
            self.assertEqual(len(calls), 1)
            second, was_cached = generate(req, root=tmp, sender=sender)
            self.assertTrue(was_cached)
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 1)
            details = json.loads(first.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual(details["transcript"], "Narration once")
            self.assertNotIn("test-only", first.with_suffix(".json").read_text())

    def test_failed_response_never_retries(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = SpeechRequest("One attempt only")
            calls = []
            def failure(*args):
                calls.append(1)
                raise RuntimeError("Simulated offline failure")
            with self.assertRaises(RuntimeError):
                generate(req, root=tmp, approval=True, api_key="test-only", sender=failure)
            with self.assertRaisesRegex(ValueError, "already had one"):
                generate(req, root=tmp, approval=True, api_key="test-only", sender=failure)
            self.assertEqual(len(calls), 1)

    def test_invalid_audio_not_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            req = SpeechRequest("Invalid bytes")
            with self.assertRaises(ValueError):
                generate(req, root=tmp, approval=True, api_key="test-only",
                         sender=lambda *args: b"not-a-wav")
            self.assertFalse((Path(tmp) / (req.identity + ".wav")).exists())


if __name__ == "__main__":
    unittest.main()
