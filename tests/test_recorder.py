import io
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from capture.ffmpeg_backend import Backend
from capture.models import CaptureOptions
from capture.recorder import Recorder, State


class StopInput(io.StringIO):
    def __init__(self, process):
        super().__init__()
        self.process = process

    def write(self, value):
        if 'q' in value:
            self.process.returncode = 0
        return super().write(value)


class FakeProcess:
    def __init__(self, command, *, progress='frame=5\n', exit_code=None, **kwargs):
        self.returncode = exit_code
        self.stdout = io.StringIO(progress)
        self.stderr = io.StringIO('device disconnected\n' if exit_code else '')
        self.stdin = StopInput(self)
        Path(command[-1]).write_bytes(b'test video')

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        self.returncode = -1

    kill = terminate


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.backend = Backend('ffmpeg', 'ffprobe', True)

    def recorder(self, **kw):
        return Recorder(self.backend, popen=kw.pop('popen', FakeProcess),
                        validator=kw.pop('validator', lambda *args: None), **kw)

    def wait_state(self, r, state):
        deadline = time.monotonic() + 3
        while r.state != state and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(r.state, state)

    def test_success_requires_frames_stop_validation_and_publish(self):
        calls = []
        r = self.recorder(validator=lambda *a: calls.append(a))
        r.start(CaptureOptions(), self.folder)
        self.wait_state(r, State.RECORDING)
        with self.assertRaises(RuntimeError):
            r.start(CaptureOptions(), self.folder)
        r.stop()
        self.assertTrue(r.wait(3))
        self.assertEqual(r.state, State.SAVED)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(list(self.folder.glob('*.mp4'))), 1)
        self.assertFalse(list(self.folder.glob('*.partial.mp4')))
        self.assertFalse(list(self.folder.glob('*.lock')))

    def test_startup_failure_never_saved(self):
        r = self.recorder(popen=lambda cmd, **kw: FakeProcess(cmd, progress='', exit_code=1, **kw))
        r.start(CaptureOptions(), self.folder)
        self.assertTrue(r.wait(3))
        self.assertEqual(r.state, State.ERROR)
        self.assertIsNone(r.started_at)
        self.assertFalse(list(self.folder.glob('*.lock')))

    def test_validation_failure_retains_partial(self):
        def invalid(*_):
            raise RuntimeError('No audio')
        r = self.recorder(validator=invalid)
        r.start(CaptureOptions(), self.folder)
        self.wait_state(r, State.RECORDING)
        r.stop()
        r.wait(3)
        self.assertEqual(r.state, State.ERROR)
        self.assertTrue(list(self.folder.glob('*.partial.mp4')))

    def test_process_launch_failure_releases_reservation(self):
        def missing(*args, **kwargs):
            raise FileNotFoundError('Missing FFmpeg')
        r = self.recorder(popen=missing)
        r.start(CaptureOptions(), self.folder)
        r.wait(3)
        self.assertEqual(r.state, State.ERROR)
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_no_frames_times_out(self):
        r = self.recorder(popen=lambda cmd, **kw: FakeProcess(cmd, progress='', **kw), startup_timeout=.1)
        r.start(CaptureOptions(), self.folder)
        self.assertTrue(r.wait(3))
        self.assertEqual(r.state, State.ERROR)

    def test_unexpected_clean_exit_is_not_success(self):
        r = self.recorder(popen=lambda cmd, **kw: FakeProcess(cmd, exit_code=0, **kw))
        r.start(CaptureOptions(), self.folder)
        r.wait(3)
        self.assertEqual(r.state, State.ERROR)

    def test_stop_before_frames_is_not_success(self):
        r = self.recorder(popen=lambda cmd, **kw: FakeProcess(cmd, progress='', **kw))
        r.start(CaptureOptions(), self.folder)
        r.stop()
        self.assertTrue(r.wait(3))
        self.assertEqual(r.state, State.ERROR)

    def test_stalled_finalization_is_terminated(self):
        processes = []
        def stubborn(cmd, **kw):
            process = FakeProcess(cmd, **kw)
            process.stdin = io.StringIO()
            processes.append(process)
            return process
        r = self.recorder(popen=stubborn, stop_timeout=.1)
        r.start(CaptureOptions(), self.folder)
        self.wait_state(r, State.RECORDING)
        r.stop()
        self.assertTrue(r.wait(3))
        self.assertEqual(r.state, State.ERROR)
        self.assertEqual(processes[0].returncode, -1)
