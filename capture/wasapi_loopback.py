"""Optional Windows WASAPI playback loopback capture; no Stereo Mix required."""
from pathlib import Path
import threading
import time
import wave
from array import array

DEVICE_ID = 'wasapi:default'
DEVICE_PREFIX = 'wasapi:index:'
FRAMES = 1024
# PCM16 peak below roughly -54 dBFS is effectively silent for ordinary
# game/browser recordings. An explicit warning is more useful than an
# incorrectly labelled successful recording.
MIN_AUDIBLE_PEAK = 65


def is_wasapi(identifier):
    return identifier == DEVICE_ID or (
        isinstance(identifier, str) and identifier.startswith(DEVICE_PREFIX)
        and identifier[len(DEVICE_PREFIX):].isdigit()
    )


def list_playback_devices():
    """Discover Windows render-loopback endpoints, not microphone inputs."""
    audio = _library()
    manager = audio.PyAudio()
    try:
        result = []
        try:
            default = _device(manager)
            result.append((DEVICE_ID, 'Windows default · ' + str(default['name'])))
        except (RuntimeError, OSError, LookupError):
            # The default may be missing while a specific output remains usable.
            pass
        for info in manager.get_loopback_device_info_generator():
            if info.get('isLoopbackDevice') and int(info.get('maxInputChannels', 0)) > 0:
                identity = DEVICE_PREFIX + str(int(info['index']))
                result.append((identity, str(info['name'])))
        return tuple(result)
    finally:
        manager.terminate()


def _library():
    try:
        import pyaudiowpatch
        return pyaudiowpatch
    except (ImportError, OSError) as exc:
        raise RuntimeError(
            'Install the optional Windows audio support first: '
            'python -m pip install -r requirements-audio.txt'
        ) from exc


def _device(manager, identifier=DEVICE_ID):
    if identifier != DEVICE_ID:
        if not is_wasapi(identifier):
            raise ValueError('Unknown playback device. Refresh audio devices.')
        index = int(identifier[len(DEVICE_PREFIX):])
        info = manager.get_device_info_by_index(index)
    else:
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
    def __init__(self, path, identifier=DEVICE_ID):
        if not is_wasapi(identifier):
            raise ValueError('Invalid Windows playback device identifier.')
        self.path = Path(path)
        self.identifier = identifier
        self._stop = threading.Event()
        self._thread = None
        self._stream = None
        self._manager = None
        self._started = threading.Event()
        self.error = None
        self.started_at = None
        self.frames = 0
        self.peak = 0
        self.stop_at = None
        self.rate = None

    def start(self):
        if self._thread:
            raise RuntimeError('Windows audio is already recording.')
        audio = _library()
        self._manager = audio.PyAudio()
        try:
            info = _device(self._manager, self.identifier)
            channels = min(2, int(info['maxInputChannels']))
            rate = round(float(info['defaultSampleRate']))
            self.rate = rate
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
                bytes_per_frame = channels * 2

                def pad_frames(count):
                    # Avoid materializing a large silence buffer for a long gap.
                    while count > 0:
                        step = min(count, rate)
                        output.writeframesraw(bytes(step * bytes_per_frame))
                        self.frames += step
                        count -= step

                while not self._stop.is_set():
                    samples = self._stream.read(FRAMES, exception_on_overflow=False)
                    received = time.monotonic()
                    if not samples:
                        raise RuntimeError('Windows audio stopped supplying samples.')
                    if len(samples) % bytes_per_frame:
                        raise RuntimeError('WASAPI returned misaligned PCM samples.')
                    block_frames = len(samples) // bytes_per_frame
                    # WASAPI loopback can temporarily block while an application
                    # is silent. A plain WAV erases those silent intervals and
                    # plays later audio too early. Restore missing wall-clock
                    # time *before* the next block. Ignore normal device jitter.
                    expected_prior = max(0, round(
                        (received - self.started_at) * rate) - block_frames)
                    missing = expected_prior - self.frames
                    if missing > max(0.12 * rate, 2 * FRAMES):
                        pad_frames(missing)
                    output.writeframesraw(samples)
                    self.frames += block_frames
                    # Audio-track presence does not prove an audible signal.
                    levels = array('h')
                    levels.frombytes(samples)
                    if levels:
                        self.peak = max(self.peak, max(abs(v) for v in levels))
                # Also retain silence at the end, when a paused loopback device
                # delivered no final samples before the user pressed Stop.
                if self.stop_at is not None:
                    trailing = round((self.stop_at - self.started_at) * rate) - self.frames
                    if trailing > 0:
                        pad_frames(trailing)
        except Exception as exc:
            if not self._stop.is_set():
                self.error = f'Windows audio recording failed: {exc}'
        finally:
            self._started.set()

    def stop(self):
        if self.stop_at is None:
            self.stop_at = time.monotonic()
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

    @property
    def duration(self):
        return self.frames / self.rate if self.rate else 0.0

    def validate(self):
        if self.error:
            raise RuntimeError(self.error)
        if self.frames < 1024 or not self.path.is_file():
            raise RuntimeError('Windows audio produced no usable samples.')
        if self.peak < MIN_AUDIBLE_PEAK:
            raise RuntimeError(
                'Windows playback was recorded but the signal was nearly silent. '
                'Choose the speaker/headphone device playing your video, then try again.'
            )
