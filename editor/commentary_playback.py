"""Local, cancellable preview of one selected Commentary Studio WAV interval.

Reads only the take's edited source range, not the whole recording. Audio I/O
is owned by one worker thread; Tk can request pause/stop but never touches a
native PortAudio stream. Original files are not modified or uploaded.
"""
from pathlib import Path
from queue import Queue
import math
import threading
import time
import wave


class TakePlayback:
    def __init__(self):
        self.events = Queue()
        self._worker = None
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._closed = False
        self._session = 0
        self._key = None
        self.position = 0.
        self.duration = 0.

    @property
    def active(self):
        return bool(self._worker and self._worker.is_alive())

    @property
    def paused(self):
        return self.active and self._pause.is_set()

    @property
    def session(self):
        return self._session

    def play(self, path, source_in, length):
        if self._closed:
            raise ValueError('Take preview has been closed.')
        path = Path(path).resolve()
        if not path.is_file():
            raise ValueError('Selected voice recording is missing.')
        if not all(type(n) in (float, int) and math.isfinite(n) for n in (source_in, length)):
            raise ValueError('Preview time must be finite.')
        if source_in < 0 or length <= 0:
            raise ValueError('Choose a positive take interval.')
        key = (str(path), float(source_in), float(length))
        if self.active:
            if self._pause.is_set() and self._key == key and not self._stop.is_set():
                self._pause.clear()
                return 'resumed'
            raise ValueError('Stop the current take before starting another.')
        self._key = key
        self._stop.clear()
        self._pause.clear()
        self.position = 0.
        self.duration = float(length)
        self._session += 1
        session = self._session
        self._worker = threading.Thread(
            target=self._run, args=(session, *key), daemon=True,
            name='Pulse commentary take playback')
        self._worker.start()
        return 'started'

    def pause(self):
        if not self.active or self._stop.is_set():
            return False
        if self._pause.is_set():
            self._pause.clear()
            return False
        self._pause.set()
        return True

    def stop(self):
        self._stop.set()
        self._pause.clear()

    def close(self):
        self._closed = True
        self.stop()
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2)

    def _run(self, session, path, source_in, length):
        manager = stream = None
        try:
            with wave.open(path, 'rb') as reader:
                if (reader.getcomptype() != 'NONE' or reader.getsampwidth() != 2
                        or reader.getnchannels() not in (1, 2)):
                    raise ValueError('Take preview needs a mono/stereo 16-bit PCM WAV.')
                rate = reader.getframerate()
                channels = reader.getnchannels()
                first = round(source_in * rate)
                if first >= reader.getnframes():
                    raise ValueError('Selected take starts beyond the recorded audio.')
                frames_left = min(round(length * rate), reader.getnframes() - first)
                if frames_left <= 0:
                    raise ValueError('Selected take is empty.')
                self.duration = frames_left / rate
                reader.setpos(first)
                if self._stop.is_set():
                    return
                try:
                    import pyaudiowpatch as audio
                except (ImportError, OSError) as exc:
                    raise RuntimeError('Audio preview needs PyAudioWPatch; install requirements-audio.txt.') from exc
                manager = audio.PyAudio()
                stream = manager.open(
                    format=audio.paInt16, channels=channels, rate=rate,
                    output=True, frames_per_buffer=1024)
                self.events.put(('started', session, ''))
                written = 0
                while frames_left and not self._stop.is_set():
                    if self._pause.is_set():
                        time.sleep(.02)
                        continue
                    frames = min(1024, frames_left)
                    data = reader.readframes(frames)
                    if not data:
                        break
                    stream.write(data)
                    count = len(data) // (2 * channels)
                    written += count
                    frames_left -= count
                    self.position = written / rate
                if not self._stop.is_set():
                    self.events.put(('finished', session, ''))
        except Exception as exc:
            if not self._stop.is_set():
                self.events.put(('error', session, str(exc)))
        finally:
            # PortAudio objects are always closed by the thread that owns them.
            if stream is not None:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if manager is not None:
                try:
                    manager.terminate()
                except Exception:
                    pass
