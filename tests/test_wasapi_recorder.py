"""Recorder lifecycle with mocked WASAPI audio: no actual hardware needed."""
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import Backend
from capture.models import CaptureOptions
from capture.recorder import Recorder, State
from capture.wasapi_loopback import DEVICE_ID
from tests.test_recorder import FakeProcess


class FakeCapture:
    instances = []

    def __init__(self, path, identifier=DEVICE_ID):
        self.path = Path(path)
        self.identifier = identifier
        self.started_at = None
        self.error = None
        self.stopped = False
        self.__class__.instances.append(self)

    def start(self):
        self.started_at = time.monotonic()
        self.path.write_bytes(b'system wav')

    def stop(self):
        self.stopped = True

    def validate(self):
        if not self.stopped:
            raise RuntimeError('audio still open')


class RecorderWASAPITests(unittest.TestCase):
    def test_only_system_audio_is_merged_before_publish(self):
        with TemporaryDirectory() as folder:
            calls = []
            def validate(probe, path, expect_audio):
                calls.append((str(path), expect_audio))
                return {'format': {'duration': 2.0}}

            def merge(ffmpeg, video, wav, destination, duration, mic, offset):
                self.assertTrue(Path(wav).is_file())
                self.assertFalse(mic)
                self.assertEqual(duration, 2.0)
                Path(destination).write_bytes(b'video+system-audio')

            with patch('capture.recorder.SystemAudioCapture', FakeCapture), \
                 patch('capture.recorder.merge_audio', side_effect=merge):
                recorder = Recorder(Backend('ffmpeg', 'ffprobe', True),
                                    popen=FakeProcess, validator=validate)
                recorder.start(CaptureOptions(audio=(DEVICE_ID,)), Path(folder))
                deadline = time.monotonic() + 3
                while recorder.state != State.RECORDING and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertEqual(recorder.state, State.RECORDING)
                recorder.stop()
                self.assertTrue(recorder.wait(3))
                self.assertEqual(recorder.state, State.SAVED)
            self.assertEqual([expect for _, expect in calls], [False, True])
            self.assertTrue(FakeCapture.instances[-1].stopped)
            self.assertEqual(len(list(Path(folder).glob('*.mp4'))), 1)
            self.assertFalse(list(Path(folder).glob('*.wasapi.wav')))

    def test_missing_system_audio_cannot_be_reported_saved(self):
        class Broken(FakeCapture):
            def start(self):
                raise RuntimeError('No WASAPI audio device')
        with TemporaryDirectory() as folder:
            with patch('capture.recorder.SystemAudioCapture', Broken):
                recorder = Recorder(Backend('ffmpeg', 'ffprobe', True),
                                    popen=FakeProcess, validator=lambda *args: None)
                recorder.start(CaptureOptions(audio=(DEVICE_ID,)), Path(folder))
                self.assertTrue(recorder.wait(3))
                self.assertEqual(recorder.state, State.ERROR)
                self.assertFalse(list(Path(folder).glob('*.mp4')))


if __name__ == '__main__':
    unittest.main()
