"""Offline narration preservation, processing, catalogue and microphone lifecycle checks."""
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import shutil
import struct
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from editor.voice_assets import VoiceSettings, digest, import_audio, process_voice, wav_info, waveform
from editor.voice_catalogue import Catalogue, Voice
from editor.voice_recording import MicrophoneRecorder
from editor.narration import Narration


def tone(path, seconds=2, frequency=440):
    rate = 24000
    with wave.open(str(path), 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b''.join(struct.pack('<h', round(8000*math.sin(2*math.pi*frequency*i/rate)))
                                   for i in range(int(seconds*rate))))


class VoiceStudioTests(unittest.TestCase):
    def test_catalogue_search_categories_favourites_and_recent_persist(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalogue = Catalogue(tmp)
            for presentation in ('Male', 'Female', 'Androgynous'):
                voice = Voice(presentation, presentation+' custom', 'missing.pth', presentation=presentation,
                              categories=('Comedy',), provenance='Test fixture only')
                catalogue.state['custom'].append(asdict(voice))
            catalogue.favourite('Female')
            catalogue.used('Male')
            loaded = Catalogue(tmp)
            self.assertEqual(loaded.search(category='Female')[0].id, 'Female')
            self.assertEqual(len(loaded.search(category='Comedy')), 3)
            self.assertEqual(loaded.search(favourites=True)[0].id, 'Female')
            self.assertEqual(loaded.search(sort='Recently used')[0].id, 'Male')
            self.assertEqual(loaded.search('British')[0].id, 'en-br')
            self.assertFalse(loaded.search(category='Female')[0].installed)

    def test_control_bounds(self):
        for field, value in [('speed', 0), ('speed', float('nan')), ('pitch', 13), ('mix', 1.1), ('volume', -1)]:
            with self.assertRaises(ValueError):
                VoiceSettings(**{field:value}).validate()
        self.assertNotIn('stop_periods=-1', VoiceSettings(trim_edges=True).filters())

    def test_microphone_pause_resume_and_original_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = MicrophoneRecorder(tmp)
            class Stream:
                def read(self, count, **kwargs):
                    time.sleep(.01)
                    return b'\x10\x00' * count
                def stop_stream(self): pass
                def close(self): pass
            class Manager:
                def get_device_info_by_index(self, index):
                    return {'name':'Test microphone', 'maxInputChannels':1, 'defaultSampleRate':48000, 'isLoopbackDevice':False}
                def open(self, **kwargs):
                    self.options = kwargs
                    return Stream()
                def terminate(self): pass
            with patch.dict('sys.modules', {'pyaudiowpatch':SimpleNamespace(PyAudio=Manager, paInt16=8)}):
                recorder.start(0)
                time.sleep(.08)
                recorder.pause()
                time.sleep(.04)
                paused = recorder.frames
                time.sleep(.04)
                self.assertEqual(recorder.frames, paused)
                recorder.pause()
                time.sleep(.05)
                recorder.stop()
                recorder.worker.join(2)
                kind, path = recorder.events.get_nowait()
                self.assertEqual(kind, 'saved')
                self.assertGreater(recorder.frames, paused)
                old_hash = digest(path)
                old_frames = recorder.frames
                recorder.start(0)
                time.sleep(.04)
                recorder.stop()
                recorder.worker.join(2)
                self.assertNotEqual(path, recorder.path)
                self.assertEqual(digest(path), old_hash)
                self.assertEqual(wav_info(path)['duration'], old_frames/48000)

    def test_loopback_is_rejected(self):
        class Manager:
            def get_device_info_by_index(self, index):
                return {'isLoopbackDevice':True, 'maxInputChannels':2}
            def terminate(self): pass
        with tempfile.TemporaryDirectory() as tmp, patch.dict('sys.modules', {'pyaudiowpatch':SimpleNamespace(PyAudio=Manager)}):
            recorder = MicrophoneRecorder(tmp)
            recorder.start(4)
            recorder.worker.join(2)
            self.assertEqual(recorder.events.get_nowait()[0], 'error')

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg unavailable')
    def test_import_keeps_exact_original_and_long_narration(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA':tmp}):
            source = Path(tmp)/'source.wav'
            # 95 seconds deliberately exceeds both the old SFX and TTS limits.
            with wave.open(str(source), 'wb') as writer:
                writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(8000)
                writer.writeframes(b'\0\0' * 8000 * 95)
            original_hash = digest(source)
            result = import_audio(source, shutil.which('ffmpeg'))
            self.assertEqual(Narration(str(result)).validate(), 95)
            details = json.loads(result.with_suffix('.json').read_text())
            self.assertEqual(digest(details['original']), original_hash)
            self.assertEqual(digest(source), original_hash)
            self.assertLessEqual(len(waveform(result)), 600)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg unavailable')
    def test_pitch_and_speed_are_independent_in_real_pcm(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source.wav'
            tone(source)
            old_hash = digest(source)
            for settings, length, frequency in [(VoiceSettings(pitch=12), 2, 880),
                                                 (VoiceSettings(speed=2), 1, 440),
                                                 (VoiceSettings(speed=.5, pitch=-12), 4, 220)]:
                result = process_voice(source, shutil.which('ffmpeg'), settings, tmp)
                self.assertAlmostEqual(wav_info(result)['duration'], length, delta=.025)
                with wave.open(str(result), 'rb') as reader:
                    reader.setpos(reader.getframerate()//4)
                    data = reader.readframes(reader.getframerate()//2)
                    samples = struct.unpack('<'+'h'*(len(data)//2), data)
                    crossings = sum(a <= 0 < b for a,b in zip(samples, samples[1:]))
                    measured = crossings / (len(samples)/reader.getframerate())
                    self.assertAlmostEqual(measured, frequency, delta=8)
            self.assertEqual(digest(source), old_hash)


if __name__ == '__main__':
    unittest.main()
