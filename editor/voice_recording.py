"""Microphone-only narration recorder, independent of gameplay loopback capture."""
from array import array
from queue import Queue
import threading
import wave

from .voice_assets import MAX_SECONDS, metadata, new_path


def is_microphone(device):
    excluded = ('stereo mix', 'loopback', 'what u hear', 'sound mapper', 'primary sound capture')
    return (device['maxInputChannels'] > 0 and not device.get('isLoopbackDevice', False)
            and not any(word in device.get('name', '').lower() for word in excluded))


def microphones():
    import pyaudiowpatch as audio
    manager = audio.PyAudio()
    try:
        return [device for device in (manager.get_device_info_by_index(i)
                for i in range(manager.get_device_count()))
                if is_microphone(device)]
    finally:
        manager.terminate()


class MicrophoneRecorder:
    def __init__(self, root=None):
        self.root = root
        self.events = Queue()
        self.stop_event = threading.Event()
        self.paused = threading.Event()
        self.worker = None
        self.level = 0.
        self.frames = 0
        self.rate = 48000
        self.path = None

    @property
    def active(self):
        return bool(self.worker and self.worker.is_alive())

    def start(self, device_index):
        if self.active:
            raise ValueError('Stop the current take first.')
        self.stop_event.clear()
        self.paused.clear()
        self.frames = 0
        self.path = new_path('recording', self.root)
        self.worker = threading.Thread(target=self._record, args=(device_index,), daemon=True)
        self.worker.start()

    def pause(self):
        if self.paused.is_set():
            self.paused.clear()
        else:
            self.paused.set()

    def stop(self):
        self.stop_event.set()

    def _record(self, device_index):
        manager = stream = None
        try:
            import pyaudiowpatch as audio
            manager = audio.PyAudio()
            device = manager.get_device_info_by_index(device_index)
            if not is_microphone(device):
                raise ValueError('Select a microphone, not system audio.')
            self.rate = int(device['defaultSampleRate'])
            stream = manager.open(format=audio.paInt16, channels=1, rate=self.rate,
                                  input=True, input_device_index=device_index, frames_per_buffer=1024)
            with self.path.open('xb') as handle, wave.open(handle, 'wb') as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(self.rate)
                while not self.stop_event.is_set() and self.frames < self.rate * MAX_SECONDS:
                    block = stream.read(1024, exception_on_overflow=True)
                    samples = array('h', block)
                    self.level = max(map(abs, samples), default=0) / 32768
                    if not self.paused.is_set():
                        writer.writeframesraw(block)
                        self.frames += len(samples)
            if not self.frames:
                raise ValueError('No microphone samples captured. Original take retained.')
            metadata(self.path, {'kind': 'microphone', 'device': device['name'],
                                 'pause_behavior': 'Record-button pauses omitted; spoken silences preserved'})
            self.events.put(('saved', self.path))
        except Exception as exc:
            self.events.put(('error', f'{exc} Take retained at {self.path}'))
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            if manager:
                manager.terminate()
            self.level = 0.
