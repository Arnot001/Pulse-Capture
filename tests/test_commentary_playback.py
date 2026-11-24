"""No-speaker tests for real Play/Pause/Resume/Stop of an edited commentary WAV."""
from array import array
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys
import time
import unittest
import wave

from editor.commentary_playback import TakePlayback


def pcm(path, frames=48000, channels=1, rate=48000):
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        # Distinct frame number helps check trimmed playback begins at source_in.
        samples = array('h', (i % 20000 for i in range(frames)
                               for _ in range(channels)))
        out.writeframes(samples.tobytes())


class PlaybackTests(unittest.TestCase):
    def wait(self, test, timeout=3):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if test():
                return
            time.sleep(.006)
        self.fail('Playback worker did not reach the requested state')

    def test_plays_only_selected_segment_and_keeps_file_intact(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'take.wav'
            pcm(path, frames=48000, channels=2)
            original = path.read_bytes()
            written = []
            opened = []
            class Stream:
                def write(self, data):
                    written.append(data)
                def stop_stream(self): pass
                def close(self): pass
            class Manager:
                def open(self, **kw):
                    opened.append(kw)
                    return Stream()
                def terminate(self): pass
            audio = SimpleNamespace(PyAudio=Manager, paInt16=8)
            player = TakePlayback()
            with patch.dict(sys.modules, {'pyaudiowpatch': audio}):
                self.assertEqual(player.play(path, .25, .125), 'started')
                self.wait(lambda: not player.active)
            result = array('h')
            result.frombytes(b''.join(written))
            self.assertEqual(len(result), 6000 * 2)
            self.assertEqual(result[0], 12000)
            self.assertEqual(result[1], 12000)
            self.assertEqual(opened[0]['channels'], 2)
            self.assertEqual(opened[0]['rate'], 48000)
            self.assertFalse(opened[0].get('input', False))
            self.assertAlmostEqual(player.position, .125, places=3)
            self.assertEqual(path.read_bytes(), original)
            events = []
            while not player.events.empty():
                events.append(player.events.get_nowait()[0])
            self.assertEqual(events, ['started', 'finished'])
            player.close()

    def test_pause_resume_stops_pcm_progress_then_continues(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'take.wav'
            pcm(path, frames=48000)
            class Stream:
                def write(self, _data):
                    time.sleep(.004)
                def stop_stream(self): pass
                def close(self): pass
            class Manager:
                def open(self, **_kw): return Stream()
                def terminate(self): pass
            player = TakePlayback()
            with patch.dict(sys.modules, {'pyaudiowpatch': SimpleNamespace(PyAudio=Manager,paInt16=8)}):
                player.play(path, 0, 1)
                self.wait(lambda: player.position > .12)
                self.assertTrue(player.pause())
                self.wait(lambda: player.paused)
                time.sleep(.028)
                settled = player.position
                time.sleep(.06)
                self.assertEqual(player.position, settled)
                self.assertEqual(player.play(path, 0, 1), 'resumed')
                self.wait(lambda: not player.active)
            self.assertAlmostEqual(player.position, 1, delta=.02)
            player.close()

    def test_stop_interrupts_audio_without_deleting_take(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'take.wav'
            pcm(path, frames=96000)
            class Stream:
                def write(self, _data): time.sleep(.010)
                def stop_stream(self): pass
                def close(self): pass
            class Manager:
                def open(self, **_kw): return Stream()
                def terminate(self): pass
            player = TakePlayback()
            with patch.dict(sys.modules, {'pyaudiowpatch': SimpleNamespace(PyAudio=Manager,paInt16=8)}):
                player.play(path, 0, 2)
                self.wait(lambda: player.position > .06)
                player.stop()
                self.wait(lambda: not player.active)
            self.assertLess(player.position, 1.5)
            self.assertTrue(path.is_file())
            player.close()

    def test_invalid_ranges_and_missing_audio_backend_report_errors(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'take.wav'
            pcm(path, frames=4800)
            player = TakePlayback()
            for a, b in ((-1,1),(0,0),(float('nan'),1)):
                with self.assertRaises(ValueError):
                    player.play(path,a,b)
            with patch.dict(sys.modules, {'pyaudiowpatch': None}):
                player.play(path, 0, .10)
                self.wait(lambda: not player.active)
            errors = []
            while not player.events.empty():
                event,_,details=player.events.get_nowait()
                if event == 'error':
                    errors.append(details)
            self.assertEqual(len(errors), 1)
            self.assertIn('PyAudioWPatch', errors[0])
            player.close()


if __name__ == '__main__':
    unittest.main()
