"""Mocked microphone lifecycle: separate mic, correct WAV and saved retakes."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys
import time
import unittest

from editor.voice_recording import MicrophoneRecorder, is_microphone, microphones, microphone_formats
from editor.voice_assets import digest, wav_info


class MicrophoneTests(unittest.TestCase):
    def test_chooses_real_mic_not_system_playback(self):
        self.assertTrue(is_microphone({'maxInputChannels':1,'name':'USB microphone'}))
        self.assertFalse(is_microphone({'maxInputChannels':2,'name':'Stereo Mix'}))
        self.assertFalse(is_microphone({'maxInputChannels':1,'name':'Mic',
                                        'isLoopbackDevice':True}))

    def test_windows_generic_default_input_is_not_filtered_as_loopback(self):
        for name in ('Microsoft Sound Mapper - Input', 'Primary Sound Capture Driver'):
            self.assertTrue(is_microphone({
                'maxInputChannels': 2, 'name': name,
                'isLoopbackDevice': False}), name)
        for name in ('Stereo Mix (Realtek Audio)', 'What U Hear',
                     'Virtual-Audio-Capturer', 'Speakers Loopback'):
            self.assertFalse(is_microphone({'maxInputChannels': 2, 'name': name}), name)

    def test_discovers_default_mapper_when_named_microphone_unavailable(self):
        entries = (
            {'index':0,'name':'Speakers Loopback','maxInputChannels':2,'isLoopbackDevice':True},
            {'index':1,'name':'Microsoft Sound Mapper - Input','maxInputChannels':2},
            {'index':2,'name':'Primary Sound Capture Driver','maxInputChannels':2},
        )
        class Manager:
            closed = False
            def get_device_count(self): return len(entries)
            def get_device_info_by_index(self,index): return entries[index]
            def terminate(self): self.closed = True
        with patch.dict(sys.modules, {'pyaudiowpatch': SimpleNamespace(PyAudio=Manager)}):
            found = microphones()
        self.assertEqual([d['index'] for d in found], [1,2])

    def test_started_event_precedes_saved_wav_and_retakes_preserve_source(self):
        with TemporaryDirectory() as folder:
            class Stream:
                def read(self,count,**kwargs):
                    time.sleep(.004)
                    return b'\x10\x00'*count
                def stop_stream(self):pass
                def close(self):pass
            class Manager:
                def get_device_info_by_index(self,index):
                    return {'name':'Test USB mic','maxInputChannels':1,
                            'defaultSampleRate':48000,'isLoopbackDevice':False}
                def open(self,**kwargs):
                    self.settings=kwargs
                    return Stream()
                def terminate(self):pass
            audio=SimpleNamespace(PyAudio=Manager,paInt16=8)
            with patch.dict(sys.modules,{'pyaudiowpatch':audio}):
                recorder=MicrophoneRecorder(folder)
                recorder.start(0)
                time.sleep(.06)
                recorder.stop()
                recorder.worker.join(2)
                events=[]
                while not recorder.events.empty():
                    events.append(recorder.events.get_nowait())
                self.assertEqual([e[0] for e in events],['started','saved'])
                first=Path(events[-1][1])
                self.assertEqual(first,Path(events[0][1]))
                self.assertGreater(wav_info(first)['duration'],0)
                self.assertIsNotNone(recorder.started_at)
                original=digest(first)
                recorder.start(0)
                time.sleep(.04)
                recorder.stop()
                recorder.worker.join(2)
                self.assertNotEqual(Path(recorder.path),first)
                self.assertEqual(digest(first),original)

    def test_format_selection_stays_on_explicit_microphone(self):
        self.assertEqual(microphone_formats({'maxInputChannels':2,'defaultSampleRate':48000}),
                         [(48000,1),(48000,2),(44100,1),(44100,2)])
        self.assertEqual(microphone_formats({'maxInputChannels':1,'defaultSampleRate':16000}),
                         [(16000,1),(48000,1),(44100,1)])
        with self.assertRaises(ValueError):
            microphone_formats({'maxInputChannels':0})

    def test_stereo_fallback_creates_valid_pcm_and_preserves_frame_count(self):
        with TemporaryDirectory() as folder:
            openings=[]
            class Stream:
                def read(self,count,**kwargs):
                    time.sleep(.005)
                    return b'\x10\x00\x10\x00' * count
                def stop_stream(self):pass
                def close(self):pass
            class Manager:
                def get_device_info_by_index(self,index):
                    self.index=index
                    return {'name':'Primary Sound Capture Driver',
                            'maxInputChannels':2,'defaultSampleRate':48000}
                def open(self,**kwargs):
                    openings.append(kwargs)
                    if kwargs['channels'] == 1:
                        raise OSError(-9999,'Unanticipated host error')
                    return Stream()
                def terminate(self):pass
            audio=SimpleNamespace(PyAudio=Manager,paInt16=8)
            with patch.dict(sys.modules,{'pyaudiowpatch':audio}):
                rec=MicrophoneRecorder(folder)
                rec.start(4)
                time.sleep(.065)
                rec.stop()
                rec.worker.join(3)
                results=[]
                while not rec.events.empty():
                    results.append(rec.events.get_nowait())
                self.assertEqual([e[0] for e in results], ['started','saved'])
                self.assertTrue(all(x['input_device_index']==4 for x in openings))
                self.assertEqual([x['channels'] for x in openings],[1,2])
                info=wav_info(rec.path)
                self.assertEqual((info['channels'],info['rate']),(2,48000))
                self.assertAlmostEqual(info['duration'],rec.frames/48000)
                self.assertGreater(rec.frames,0)

    def test_failed_device_open_is_actionable_and_creates_no_fake_take(self):
        with TemporaryDirectory() as folder:
            class Manager:
                def get_device_info_by_index(self,index):
                    return {'name':'Microsoft Sound Mapper - Input',
                            'maxInputChannels':2,'defaultSampleRate':48000}
                def open(self,**kwargs):
                    raise OSError(-9999,'Unanticipated host error')
                def terminate(self):pass
            with patch.dict(sys.modules,{
                    'pyaudiowpatch': SimpleNamespace(PyAudio=Manager,paInt16=8)}):
                rec=MicrophoneRecorder(folder)
                rec.start(0)
                rec.worker.join(3)
                kind,message=rec.events.get_nowait()
                self.assertEqual(kind,'error')
                self.assertIn('Windows Settings',message)
                self.assertIn('Microphone',message)
                self.assertIn('No audio file was created',message)
                self.assertFalse(rec.path.exists())

    def test_loopback_rejected_without_starting_recording(self):
        with TemporaryDirectory() as folder:
            class Manager:
                def get_device_info_by_index(self,index):
                    return {'name':'System audio','maxInputChannels':2,
                            'isLoopbackDevice':True}
                def terminate(self):pass
            with patch.dict(sys.modules,{'pyaudiowpatch':SimpleNamespace(PyAudio=Manager)}):
                recorder=MicrophoneRecorder(folder)
                recorder.start(4)
                recorder.worker.join(2)
                self.assertEqual(recorder.events.get_nowait()[0],'error')


if __name__=='__main__':
    unittest.main()
