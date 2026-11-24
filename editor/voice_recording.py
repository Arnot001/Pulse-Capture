"""Microphone-only narration recorder, independent of gameplay loopback capture."""
from array import array
from queue import Queue
import threading
import time
import wave

from .voice_assets import MAX_SECONDS, metadata, new_path


def is_microphone(device):
    """Allow Windows' generic *input* routes while excluding audio loopback.

    PortAudio sometimes exposes an actual headset microphone only through
    'Microsoft Sound Mapper - Input' / 'Primary Sound Capture Driver'.
    Filtering those generic input aliases made the Commentary dropdown empty
    even though Windows could record audio. They refer to the user's selected
    Windows default recording device, not an automatically chosen microphone.
    """
    excluded = ('stereo mix', 'stereomix', 'loopback', 'what u hear',
                'what you hear', 'wave out mix', 'waveout mix',
                'virtual-audio-capturer')
    return (device.get('maxInputChannels', 0) > 0
            and not device.get('isLoopbackDevice', False)
            and not any(word in device.get('name', '').lower() for word in excluded))


def microphones():
    import pyaudiowpatch as audio
    manager = audio.PyAudio()
    try:
        devices = [device for device in (manager.get_device_info_by_index(i)
                   for i in range(manager.get_device_count()))
                   if is_microphone(device)]
        # Put individually named microphones before Windows default aliases;
        # the latter remain selectable if they're the only input route.
        defaults = ('sound mapper', 'primary sound capture')
        return sorted(devices, key=lambda d: (
            any(x in d.get('name', '').lower() for x in defaults),
            d.get('name', '').lower()))
    finally:
        manager.terminate()


def microphone_formats(device):
    """Probe only the user's selected input, never change devices silently.

    Some Windows generic recording devices report two channels but reject
    mono capture, or reject the default sample rate at a different channel
    count. Keep the list small and deterministic to avoid PortAudio thrashing.
    """
    maximum = int(device.get('maxInputChannels', 0))
    if maximum < 1:
        raise ValueError('Selected input does not have a recording channel.')
    reported = device.get('defaultSampleRate')
    rates = []
    try:
        nominal = round(float(reported))
        if 8000 <= nominal <= 96000:
            rates.append(nominal)
    except (TypeError, ValueError, OverflowError):
        pass
    for rate in (48000, 44100):
        if rate not in rates:
            rates.append(rate)
    channels = [1] + ([2] if maximum >= 2 else [])
    return [(rate, channel) for rate in rates[:3] for channel in channels]


def open_microphone(manager, audio, device_index, device):
    """Try supported mono/stereo PCM on one explicit device only.

    Return the stream's real channel count and sample rate for the WAV header.
    No fallback to system loopback, another input, or implicit defaults.
    """
    attempted = []
    for rate, channels in microphone_formats(device):
        try:
            stream = manager.open(
                format=audio.paInt16, channels=channels, rate=rate,
                input=True, input_device_index=device_index,
                frames_per_buffer=1024)
            return stream, rate, channels
        except (OSError, ValueError) as exc:
            attempted.append(f'{rate}Hz/{channels}ch: {exc}')
    name = device.get('name', 'Unknown recording input')
    details = '; '.join(attempted)
    raise ValueError(
        f"Windows couldn't open recording input '{name}' (#{device_index}). "
        f"Tested {details}. In Windows Settings > System > Sound > Input, "
        "check that a real microphone is connected, selected as default and "
        "responds to speech. Check Settings > Privacy & security > Microphone "
        "and allow desktop apps to access the mic. Close apps using the "
        "microphone exclusively, then refresh the device list."
    )


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
        self.started_at = None

    @property
    def active(self):
        return bool(self.worker and self.worker.is_alive())

    def start(self, device_index):
        if self.active:
            raise ValueError('Stop the current take first.')
        self.stop_event.clear()
        self.paused.clear()
        self.frames = 0
        self.started_at = None
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
            stream, self.rate, channels = open_microphone(
                manager, audio, device_index, device)
            with self.path.open('xb') as handle, wave.open(handle, 'wb') as writer:
                writer.setnchannels(channels)
                writer.setsampwidth(2)
                writer.setframerate(self.rate)
                self.started_at = time.monotonic()
                self.events.put(('started', self.path))
                while not self.stop_event.is_set() and self.frames < self.rate * MAX_SECONDS:
                    block = stream.read(1024, exception_on_overflow=True)
                    samples = array('h', block)
                    self.level = max(map(abs, samples), default=0) / 32768
                    if not self.paused.is_set():
                        writer.writeframesraw(block)
                        self.frames += len(samples) // channels
            if not self.frames:
                raise ValueError('No microphone samples captured. Original take retained.')
            metadata(self.path, {'kind': 'microphone', 'device': device['name'],
                                 'device_index': device_index, 'channels': channels,
                                 'sample_rate': self.rate,
                                 'pause_behavior': 'Record-button pauses omitted; spoken silences preserved'})
            self.events.put(('saved', self.path))
        except Exception as exc:
            retained = (f' Original WAV retained at {self.path}.'
                        if self.path is not None and self.path.is_file() else
                        ' No audio file was created.')
            self.events.put(('error', f'{exc}{retained}'))
        finally:
            if stream:
                stream.stop_stream()
                stream.close()
            if manager:
                manager.terminate()
            self.level = 0.
