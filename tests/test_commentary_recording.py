"""Mocked microphone lifecycle: separate mic, correct WAV and saved retakes."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import sys
import time
import unittest

from editor.voice_recording import MicrophoneRecorder, is_microphone
from editor.voice_assets import digest, wav_info


class MicrophoneTests(unittest.TestCase):
    def test_chooses_real_mic_not_system_playback(self):
        self.assertTrue(is_microphone({'maxInputChannels':1,'name':'USB microphone'}))
        self.assertFalse(is_microphone({'maxInputChannels':2,'name':'Stereo Mix'}))
        self.assertFalse(is_microphone({'maxInputChannels':1,'name':'Mic',
                                        'isLoopbackDevice':True}))

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
