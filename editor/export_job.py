"""Cancelable background exports with real progress and validation before publishing."""
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
import subprocess
import threading
import time
from capture.ffmpeg_backend import process_options, validate_output
from .ffmpeg_export import build_export_command
from .filenames import reserve_export
from .transforms import EditOptions
from .text_overlay import TextResources


@dataclass(frozen=True)
class ExportEvent:
    kind: str
    progress: float = 0
    message: str = ''
    path: Path | None = None


class ExportCancelled(Exception):
    pass


class ExportJob:
    def __init__(self, backend, *, popen=subprocess.Popen, validator=validate_output):
        self.backend, self._popen, self._validator = backend, popen, validator
        self.events = Queue()
        self.busy = False
        self._cancel = threading.Event()
        self._worker = None

    def start(self, media, trim, folder=None, edits=None):
        if self.busy:
            raise RuntimeError('An export is already running.')
        trim.validate(media)
        edits = edits or EditOptions()
        edits.validate(media)
        self._cancel.clear()
        self.busy = True
        self._worker = threading.Thread(target=self._run, args=(media, trim, folder, edits), daemon=True)
        self._worker.start()

    def cancel(self):
        self._cancel.set()

    def wait(self, timeout=None):
        if self._worker:
            self._worker.join(timeout)
        return not self._worker or not self._worker.is_alive()

    def _check_cancel(self):
        if self._cancel.is_set():
            raise ExportCancelled()

    def _progress(self, stream, duration):
        for line in stream:
            key, _, value = line.strip().partition('=')
            if key == 'out_time_us':
                try:
                    progress = max(0, min(.98, int(value) / 1_000_000 / duration))
                    self.events.put(ExportEvent('progress', progress))
                except ValueError:
                    pass

    @staticmethod
    def _drain(stream, log):
        for line in stream:
            log.append(line.rstrip())

    def _run(self, media, trim, folder, edits):
        reservation = process = resources = None
        readers, log = [], deque(maxlen=30)
        result = ExportEvent('error', message='Export did not finish.')
        try:
            self._check_cancel()
            resources = TextResources(edits.text)
            reservation = reserve_export(media.path, folder)
            command = build_export_command(self.backend.ffmpeg, media, trim, reservation.partial, edits, text_resources=resources)
            process = self._popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, encoding='utf-8',
                                  errors='replace', bufsize=1, **process_options())
            out_duration = edits.output_duration(trim.duration)
            readers = [threading.Thread(target=self._progress, args=(process.stdout, out_duration), daemon=True),
                       threading.Thread(target=self._drain, args=(process.stderr, log), daemon=True)]
            for reader in readers:
                reader.start()
            while process.poll() is None:
                self._check_cancel()
                time.sleep(.05)
            for reader in readers:
                reader.join(timeout=2)
            self._check_cancel()
            if process.returncode:
                raise RuntimeError('The video could not be exported.\n' + '\n'.join(log)[-1600:])
            self.events.put(ExportEvent('validating', .99, 'Checking your exported video…'))
            info = self._validator(self.backend.ffprobe, reservation.partial, media.has_audio)
            duration = float(info['format']['duration'])
            if abs(duration - out_duration) > max(.15, 2 / media.fps):
                raise RuntimeError('The exported length did not match your selection. The original is unchanged.')
            self._check_cancel()
            reservation.publish()
            result = ExportEvent('saved', 1, 'Export complete', reservation.final)
        except ExportCancelled:
            result = ExportEvent('cancelled', message='Export cancelled. Your original is unchanged.')
        except Exception as exc:
            result = ExportEvent('error', message=str(exc))
        finally:
            try:
                if process:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=3)
                    for reader in readers:
                        reader.join(timeout=2)
                    for stream in (process.stdout, process.stderr):
                        if stream:
                            stream.close()
                if reservation:
                    reservation.partial.unlink(missing_ok=True)
                    reservation.release()
            except (OSError, subprocess.TimeoutExpired) as exc:
                result = ExportEvent('error', message=f'Could not finish export cleanup: {exc}')
            finally:
                try:
                    if resources:
                        resources.close()
                except OSError as exc:
                    result = ExportEvent('error', message=f'Could not remove temporary text: {exc}')
                self.busy = False
                self.events.put(result)
