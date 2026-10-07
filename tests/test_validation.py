import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from capture.ffmpeg_backend import validate_output


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'video.mp4'
        self.path.write_bytes(b'x' * 512)

    def test_missing_and_empty_file_rejected(self):
        self.path.unlink()
        with self.assertRaises(RuntimeError):
            validate_output('probe', self.path)
        self.path.touch()
        with self.assertRaises(RuntimeError):
            validate_output('probe', self.path)

    def test_positive_duration_and_video_frames_required(self):
        cases = [({}, False),
                 ({'streams': [{'codec_type': 'video', 'nb_frames': '0'}], 'format': {'duration': '1'}}, False),
                 ({'streams': [{'codec_type': 'video', 'nb_frames': '30'}], 'format': {'duration': '0'}}, False),
                 ({'streams': [{'codec_type': 'video', 'nb_frames': '30'}], 'format': {'duration': '1'}}, True)]
        for info, success in cases:
            with self.subTest(info=info), patch('capture.ffmpeg_backend.run',
                return_value=SimpleNamespace(returncode=0, stdout=json.dumps(info), stderr='')):
                if success:
                    self.assertEqual(validate_output('probe', self.path), info)
                    with self.assertRaises(RuntimeError):
                        validate_output('probe', self.path, expect_audio=True)
                else:
                    with self.assertRaises(RuntimeError):
                        validate_output('probe', self.path)

    def test_probe_error_rejected(self):
        with patch('capture.ffmpeg_backend.run', return_value=SimpleNamespace(returncode=1, stderr='bad file')):
            with self.assertRaisesRegex(RuntimeError, 'bad file'):
                validate_output('probe', self.path)
