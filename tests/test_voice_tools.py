"""Offline voice reaction tests; no Windows speaker or FFmpeg needed."""
import base64
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

from editor.voice_tools import encode_request, generate_voice_import, validate_voice_text


class FakeLibrary:
    def __init__(self):
        self.calls = []
        self.categories = []

    def import_file(self, path, kind, ffmpeg, ffprobe):
        assert Path(path).is_file()
        self.calls.append((Path(path).name, kind, ffmpeg, ffprobe))
        return 'import.0123456789abcdef'

    def categorize(self, keys, category):
        self.categories.append((keys, category))

    def update_details(self, key, details):
        self.details = details


def fake_speech(text, output):
    with wave.open(str(output), 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b'\x00\x00' * 8000)


class OfflineVoiceTests(unittest.TestCase):
    def test_ordinary_and_swearing_reactions_are_allowed(self):
        self.assertEqual(validate_voice_text('  Aw  nah, brooo!  '), 'Aw nah, brooo!')
        self.assertEqual(validate_voice_text('What the fuck?!'), 'What the fuck?!')

    def test_reject_empty_unbounded_and_wrong_type(self):
        for value in ('', ' \n ', 'x' * 141, None, 52):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_voice_text(value)

    def test_text_never_becomes_powershell_source(self):
        text = 'What the "fuck"? $env:PATH ; & Unicode café'
        payload = encode_request(text, 'C:\\Temp\\a "b".wav')
        decoded = json.loads(base64.b64decode(payload).decode('utf-8'))
        self.assertEqual(decoded['text'], text)
        self.assertEqual(decoded['output'], 'C:\\Temp\\a "b".wav')

    def test_generated_voice_uses_existing_library_and_voices_category(self):
        library = FakeLibrary()
        with patch('editor.voice_tools.synthesize_windows', side_effect=fake_speech):
            key = generate_voice_import('Aw nah, brooo!', library, 'ffmpeg', 'ffprobe')
        self.assertEqual(key, 'import.0123456789abcdef')
        self.assertEqual(library.calls, [('Voice - Aw nah brooo.wav', 'sfx', 'ffmpeg', 'ffprobe')])
        self.assertEqual(library.categories, [(['import.0123456789abcdef'], 'Voices')])
        self.assertEqual(library.details['audio_type'], 'windows_voice')

    def test_cancel_never_adds_a_library_entry(self):
        library = FakeLibrary()
        stopped = threading.Event()
        stopped.set()
        with patch('editor.voice_tools.synthesize_windows', side_effect=fake_speech):
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                generate_voice_import('Nope!', library, 'ffmpeg', 'ffprobe', stopped)
        self.assertFalse(library.calls)


if __name__ == '__main__':
    unittest.main()
