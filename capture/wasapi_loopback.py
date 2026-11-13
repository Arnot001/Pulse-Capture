"""Optional Windows WASAPI playback loopback capture; no Stereo Mix required."""
from pathlib import Path
import threading
import time
import wave

DEVICE_ID = 'wasapi:default'
FRAMES = 1024


def _library():
    try:
        import pyaudiowpatch
        return pyaudiowpatch
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            'Install the optional Windows audio support first: '
            'python -m pip install -r requirements-audio.txt'
        ) from exc


def _device(manager):
    try:
        info = manager.get_default_wasapi_loopback()
    except (OSError, LookupError) as exc:
        raise RuntimeError(
            'No WASAPI loopback for your current Windows playback device. '
            'Select working speakers/headphones and refresh devices.'
        ) from exc
    if not info or not info.get('isLoopbackDevice') or int(info.get('maxInputChannels', 0)) < 1:
        raise RuntimeError('Windows did not report a valid system-audio loopback.')
    return info


def discover_default():
    """Return (name, explanation); reported device does not guarantee sound."""
    try:
        audio = _library()
        manager = audio.PyAudio()
        try:
            return str(_device(manager)['name']), ''
        finally:
            manager.terminate()
    except Exception as exc:
        return None, str(exc)


class SystemAudioCapture:
    """A temporary local WAV is merged into the final MP4 on successful stop."""
    def __init__(self, path):
        self.path = Path(path)
        self._stop = threading.Event()
        self._thread = None
        self._stream = None
        self._manager = None
        self._started = threading.Event()
        self.error = None
        self.started_at = None
        self.frames = 0

    def start(self):
        if self._thread:
            raise RuntimeError('Windows audio is already recording.')
        audio = _library()
        self._manager = audio.PyAudio()
        try:
            info = _device(self._manager)
            channels = min(2, int(info['maxInputChannels']))
            rate = round(float(info['defaultSampleRate']))
            self._stream = self._manager.open(
                format=audio.paInt16, channels=channels, rate=rate, input=True,
                input_device_index=int(info['index']), frames_per_buffer=FRAMES)
            self._thread = threading.Thread(
                target=self._record, args=(channels, rate), daemon=True,
                name='Pulse Windows audio')
            self._thread.start()
            if not self._started.wait(5):
                raise RuntimeError('Windows audio capture did not start.')
            if self.error:
                raise RuntimeError(self.error)
        except Exception:
            self.stop()
            raise

    def _record(self, channels, rate):
        try:
            with wave.open(str(self.path), 'wb') as output:
                output.setnchannels(channels)
                output.setsampwidth(2)
                output.setframerate(rate)
                self.started_at = time.monotonic()
                self._started.set()
                while not self._stop.is_set():
                    samples = self._stream.read(FRAMES, exception_on_overflow=False)
                    if not samples:
                        raise RuntimeError('Windows audio stopped supplying samples.')
                    output.writeframesraw(samples)
                    self.frames += len(samples) // (channels * 2)
        except Exception as exc:
            if not self._stop.is_set():
                self.error = f'Windows audio recording failed: {exc}'
        finally:
            self._started.set()

    def stop(self):
        self._stop.set()
        if self._stream:
            try:
                self._stream.stop_stream()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                self.error = self.error or 'Windows audio did not stop cleanly.'
        if self._stream:
            try:
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        if self._manager:
            self._manager.terminate()
            self._manager = None

    def validate(self):
        if self.error:
            raise RuntimeError(self.error)
        if self.frames < 1024 or not self.path.is_file():
            raise RuntimeError('Windows audio produced no usable samples.')
