"""WASAPI discovery and command tests; hardware is never required."""
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from capture.audio_devices import discover_audio
from capture.ffmpeg_backend import Backend, build_command
from capture.models import CaptureOptions
from capture.wasapi_loopback import (
    DEVICE_ID, DEVICE_PREFIX, SystemAudioCapture, _device,
    discover_default, list_playback_devices)
from capture.system_audio_mux import merge_command


class FakeStream:
    def read(self, size, exception_on_overflow=False):
        time.sleep(.003)
        return b'\\x00\\x10' * (size * 2)

    def stop_stream(self):
        pass

    def close(self):
        pass


class FakeManager:
    def __init__(self):
        self.closed = False

    def get_default_wasapi_loopback(self):
        return {'name': 'Speakers (Test) [Loopback]', 'index': 7,
                'isLoopbackDevice': True, 'maxInputChannels': 2,
                'defaultSampleRate': 48000}

    def get_device_info_by_index(self, index):
        assert index == 7
        return self.get_default_wasapi_loopback()

    def get_loopback_device_info_generator(self):
        yield self.get_default_wasapi_loopback()

    def open(self, **kwargs):
        assert kwargs['input_device_index'] == 7
        return FakeStream()

    def terminate(self):
        self.closed = True


class FakeLibrary:
    paInt16 = 8

    def PyAudio(self):
        return FakeManager()


class WASAPITests(unittest.TestCase):
    def test_probes_real_loopback_not_a_microphone(self):
        with patch('capture.wasapi_loopback._library', return_value=FakeLibrary()):
            name, notice = discover_default()
            self.assertIn('Speakers', name)
            self.assertEqual(notice, '')
            with TemporaryDirectory() as folder:
                wav = Path(folder) / 'test.wav'
                capture = SystemAudioCapture(wav)
                capture.start()
                time.sleep(.03)
                capture.stop()
                capture.validate()
                self.assertGreater(wav.stat().st_size, 44)

    def test_missing_support_is_explicit(self):
        with patch('capture.wasapi_loopback._library', side_effect=RuntimeError('Install PyAudioWPatch')):
            name, notice = discover_default()
        self.assertIsNone(name)
        self.assertIn('PyAudioWPatch', notice)

    def test_inventory_can_offer_wasapi_even_without_dshow(self):
        backend = Backend('ffmpeg', 'ffprobe', False)
        with patch('capture.audio_devices.list_playback_devices',
                   return_value=((DEVICE_ID, 'Speakers (Test)'),)):
            inventory = discover_audio(backend)
        self.assertEqual(inventory.loopbacks[0].identifier, DEVICE_ID)
        self.assertEqual(inventory.microphones, ())

    def test_ffmpeg_omits_wasapi_from_dshow_input_but_keeps_mic(self):
        options = CaptureOptions(audio=('Microphone Array', DEVICE_ID))
        cmd = build_command('ffmpeg', options, 'recording.mp4')
        self.assertIn('audio=Microphone Array', cmd)
        self.assertNotIn('audio=' + DEVICE_ID, cmd)
        self.assertEqual(cmd.count('-f'), 3)  # gdigrab, dshow, output mp4
        self.assertIn('1:a:0', cmd)
        system_only = build_command('ffmpeg', CaptureOptions(audio=(DEVICE_ID,)), 'out.mp4')
        self.assertIn('-an', system_only)
        self.assertNotIn('audio=' + DEVICE_ID, system_only)

    def test_mux_uses_copy_video_and_mixes_two_sources(self):
        cmd = merge_command('ffmpeg', 'base.mp4', 'system.wav', 'merged.mp4',
                            4.2, True, .15)
        self.assertIn('-ss', cmd)
        self.assertIn('0:v:0', cmd)
        self.assertIn('amix=inputs=2', ' '.join(cmd))
        self.assertIn('copy', cmd)
        self.assertEqual(cmd[-1], 'merged.mp4')
        only = merge_command('ffmpeg', 'base.mp4', 'system.wav', 'merged.mp4',
                             4.2, False, -.1)
        self.assertIn('-itsoffset', only)
        self.assertNotIn('-filter_complex', only)
        self.assertIn('1:a:0', only)

    def test_enumerate_selected_loopback_endpoint(self):
        with patch('capture.wasapi_loopback._library', return_value=FakeLibrary()):
            outputs = list_playback_devices()
            self.assertEqual(outputs[0][0], DEVICE_ID)
            self.assertEqual(outputs[1][0], DEVICE_PREFIX+'7')
            with TemporaryDirectory() as folder:
                session = SystemAudioCapture(Path(folder) / 'output.wav', DEVICE_PREFIX+'7')
                session.start()
                time.sleep(.03)
                session.stop()
                session.validate()

    def test_silent_system_audio_is_reported_as_failure(self):
        class SilentStream(FakeStream):
            def read(self, size, exception_on_overflow=False):
                return bytes(size * 4)
        class SilentManager(FakeManager):
            def open(self, **kwargs):
                return SilentStream()
        class SilentLibrary(FakeLibrary):
            def PyAudio(self):
                return SilentManager()
        with patch('capture.wasapi_loopback._library', return_value=SilentLibrary()):
            with TemporaryDirectory() as folder:
                session = SystemAudioCapture(Path(folder) / 'silent.wav')
                session.start()
                time.sleep(.02)
                session.stop()
                with self.assertRaisesRegex(RuntimeError, 'nearly silent'):
                    session.validate()

    def test_invalid_loopback_is_rejected(self):
        class Wrong(FakeManager):
            def get_default_wasapi_loopback(self):
                return {'isLoopbackDevice': False, 'maxInputChannels': 2}
        with self.assertRaisesRegex(RuntimeError, 'valid system-audio loopback'):
            _device(Wrong())


if __name__ == '__main__':
    unittest.main()
