"""Threaded state machine. Tk never touches the child process or worker threads."""
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from queue import Queue
import subprocess
import threading
import time
from .ffmpeg_backend import build_command, process_options, validate_output
from .filenames import reserve


class State(str, Enum):
    IDLE = 'idle'
    STARTING = 'starting'
    RECORDING = 'recording'
    STOPPING = 'stopping'
    SAVED = 'saved'
    ERROR = 'error'


@dataclass(frozen=True)
class Event:
    state: State
    message: str = ''
    path: Path | None = None


class Recorder:
    def __init__(self, backend, *, popen=subprocess.Popen, validator=validate_output,
                 startup_timeout=20, stop_timeout=30):
        self.backend, self._popen, self._validator = backend, popen, validator
        self.startup_timeout, self.stop_timeout = startup_timeout, stop_timeout
        self.events = Queue()
        self.state = State.IDLE
        self.started_at = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._frames = threading.Event()
        self._worker = None
        self._process = None

    @property
    def busy(self):
        return self.state in (State.STARTING, State.RECORDING, State.STOPPING)

    def _set(self, state, message='', path=None):
        with self._lock:
            self.state = state
            self.events.put(Event(state, message, path))

    def start(self, options, folder):
        options.validate()
        with self._lock:
            if self.busy:
                raise RuntimeError('A recording is already in progress.')
            self._stop.clear()
            self._frames.clear()
            self.started_at = None
            self._set(State.STARTING)
            self._worker = threading.Thread(target=self._record, args=(options, folder), daemon=True)
            self._worker.start()

    def stop(self):
        with self._lock:
            if self.state in (State.STARTING, State.RECORDING):
                self._stop.set()
                self._set(State.STOPPING)

    def wait(self, timeout=None):
        if self._worker:
            self._worker.join(timeout)
        return not self._worker or not self._worker.is_alive()

    def _read_progress(self, stream):
        for line in stream:
            key, _, value = line.strip().partition('=')
            if key == 'frame' and value.strip().isdigit() and int(value) > 0:
                with self._lock:
                    self._frames.set()
                    if self.state == State.STARTING and not self._stop.is_set():
                        self.started_at = time.monotonic()
                        self._set(State.RECORDING)

    @staticmethod
    def _drain(stream, log):
        for line in stream:
            log.append(line.rstrip())

    @staticmethod
    def _terminate(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    def _record(self, options, folder):
        reservation, process = None, None
        readers, log = [], deque(maxlen=60)
        failure, saved = None, None
        try:
            reservation = reserve(folder)
            command = build_command(self.backend.ffmpeg, options, reservation.partial)
            process = self._popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                  errors='replace', bufsize=1, **process_options())
            self._process = process
            readers = [threading.Thread(target=self._read_progress, args=(process.stdout,), daemon=True),
                       threading.Thread(target=self._drain, args=(process.stderr, log), daemon=True)]
            for thread in readers:
                thread.start()
            deadline = time.monotonic() + self.startup_timeout
            stop_deadline = None
            while process.poll() is None:
                if self._stop.is_set() and stop_deadline is None:
                    try:
                        process.stdin.write('q\n')
                        process.stdin.flush()
                    except (BrokenPipeError, OSError):
                        pass
                    stop_deadline = time.monotonic() + self.stop_timeout
                if stop_deadline and time.monotonic() > stop_deadline:
                    raise RuntimeError('FFmpeg did not finish in time. The partial recording was retained.')
                if not self._frames.is_set() and stop_deadline is None and time.monotonic() > deadline:
                    raise RuntimeError('FFmpeg did not deliver video frames. Check the capture target and audio permissions.')
                time.sleep(0.05)
            for thread in readers:
                thread.join(timeout=2)
            if process.returncode != 0:
                raise RuntimeError('FFmpeg stopped with an error.\n' + '\n'.join(log)[-2500:])
            if not self._stop.is_set():
                raise RuntimeError('Recording ended unexpectedly. The partial file was retained.')
            if not self._frames.is_set():
                raise RuntimeError('Recording stopped before any video frames were captured.')
            self._validator(self.backend.ffprobe, reservation.partial, bool(options.audio))
            reservation.publish()
            saved = reservation.final
        except Exception as exc:
            failure = str(exc)
        finally:
            if process:
                try:
                    self._terminate(process)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    failure = failure or str(exc)
                for thread in readers:
                    thread.join(timeout=2)
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        stream.close()
            self._process = None
            if reservation:
                try:
                    if reservation.partial.exists() and reservation.partial.stat().st_size == 0:
                        reservation.partial.unlink()
                    reservation.release()
                except OSError as exc:
                    failure = failure or str(exc)
            if failure:
                partial = reservation.partial if reservation and reservation.partial.exists() else None
                self._set(State.ERROR, failure, partial)
            elif saved:
                self._set(State.SAVED, path=saved)
