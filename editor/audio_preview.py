"""Audible Quick Edit preview: play source audio + music without rendering video.

FFmpeg decodes only the audio kept by Trim/Cut, applies clip speed and volumes,
and produces PCM. PyAudioWPatch sends that PCM to the current Windows output.
No audio is stored or uploaded. Video preview remains the existing frame worker.
"""
from queue import Queue
import subprocess
import threading
import time

from capture.ffmpeg_backend import process_options
from .cuts import CutPlan
from .music import resolve_music_path
from .music_mix import input_loops, filters as soundtrack_filters, duck
from .polish import audio_tempo_filters
from .transforms import EditOptions


SAMPLE_RATE = 48000
BLOCK_BYTES = 8192


def audio_preview_command(ffmpeg, media, source_position, trim, cuts=None,
                          edits=None, music_path=None):
    """Build an FFmpeg audio-only command aligned with the visible output time."""
    edits = edits or EditOptions()
    cuts = cuts or CutPlan()
    trim.validate(media)
    cuts.validate_selection(media, trim)
    edits.validate(media)
    if not media.has_audio and not edits.music.enabled and not edits.sounds and not edits.narration:
        return None
    start = cuts.snap_position(source_position, trim)
    remaining = tuple((max(start, part.start), part.end)
                      for part in cuts.kept_segments(trim) if part.end > start + 1e-9)
    remaining = tuple((a, b) for a, b in remaining if b > a)
    if not remaining:
        return None
    duration = sum(b-a for a, b in remaining) / edits.speed
    if duration <= 0:
        return None
    output_offset = cuts.source_elapsed(start, trim) / edits.speed
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-i', str(media.path)]
    if edits.music.enabled:
        music_path = music_path or resolve_music_path(edits.music)
        if input_loops(edits.music):
            args += ['-stream_loop', '-1']
        args += ['-i', str(music_path)]
    graph = []
    if media.has_audio:
        labels = []
        for i, (start_at, end_at) in enumerate(remaining):
            label = f'piece{i}'
            graph.append(f'[0:a:0]atrim=start={start_at:.9f}:end={end_at:.9f},'
                         f'asetpts=PTS-STARTPTS[{label}]')
            labels.append(label)
        if len(labels) == 1:
            combined = labels[0]
        else:
            graph.append(''.join(f'[{name}]' for name in labels) +
                         f'concat=n={len(labels)}:v=0:a=1[joined]')
            combined = 'joined'
        source_filters = list(audio_tempo_filters(edits.speed))
        if edits.music.enabled and edits.music.original_volume != 1:
            source_filters.append(f'volume={edits.music.original_volume:g}')
        source_filters.append('aresample=async=1:first_pts=0')
        graph.append(f'[{combined}]{",".join(source_filters)}[source]')
    if edits.music.enabled:
        music_filters = soundtrack_filters(edits.music,duration,output_offset,output_offset+duration)
        graph.append(f'[1:a:0]{",".join(music_filters)}[music]')
    if media.has_audio and edits.music.enabled:
        source_label,music_label = ('source','music')
        if edits.music.duck_dialogue:
            source_label,music_label = duck(graph,source_label,music_label,'previewduck')
        graph.append(f'[{source_label}][{music_label}]amix=inputs=2:duration=longest:'
                     'dropout_transition=0:normalize=0,'
                     'alimiter=limit=0.95:level=false:latency=true[aout]')
    elif media.has_audio or edits.music.enabled:
        label = 'source' if media.has_audio else 'music'
        graph.append(f'[{label}]anull[aout]')
    result = 'aout' if media.has_audio or edits.music.enabled else None
    if edits.sounds:
        from .reactions import add_sounds
        result = add_sounds(args, graph, result, edits.sounds, duration, output_offset)
    if edits.narration:
        from .narration import add_narration
        result = add_narration(args, graph, result, edits.narration, duration, output_offset)
    if result is None:
        return None
    args += ['-filter_complex', ';'.join(graph), '-map', f'[{result}]',
             '-t', f'{duration:.9f}', '-ac', '2', '-ar', str(SAMPLE_RATE),
             '-c:a', 'pcm_s16le', '-f', 's16le', 'pipe:1']
    return args


class AudioPlayback:
    """Serialize native audio lifetime on exactly one owner thread.

    The Tk thread may request play/stop/seek and terminate the FFmpeg *child*
    process to wake a blocked pipe, but it never calls PortAudio stream methods.
    A new playback starts only after the previous session's stream is closed.
    """

    def __init__(self, ffmpeg, media):
        self.ffmpeg, self.media = ffmpeg, media
        self.errors = Queue()
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._worker = None
        self._process = None
        self._closed = False
        self._pending = None
        self._active_cancel = None
        self._audio_clock_start = None
        self._audio_failed = False
        self._play_requested_at = None

    def _interrupt_locked(self):
        if self._active_cancel is not None:
            self._active_cancel.set()
        # Terminating a child process is safe here. Only the worker touches
        # native PortAudio methods, and the worker alone closes its streams.
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def play(self, position, trim, cuts, edits):
        with self._wake:
            if self._closed:
                return
            self._interrupt_locked()
            self._audio_clock_start = None
            self._audio_failed = False
            self._play_requested_at = time.monotonic()
            self._pending = (position, trim, cuts, edits) if (
                self.media.has_audio or edits.music.enabled or edits.sounds or edits.narration) else None
            if self._pending and (self._worker is None or not self._worker.is_alive()):
                self._worker = threading.Thread(
                    target=self._run, daemon=True, name='Pulse edit audio output')
                self._worker.start()
            self._wake.notify_all()

    def elapsed(self):
        with self._lock:
            if self._audio_clock_start is not None:
                return max(0.0, time.monotonic() - self._audio_clock_start)
            if self._audio_failed and self._play_requested_at is not None:
                return max(0.0, time.monotonic() - self._play_requested_at)
            return None

    def stop(self):
        with self._wake:
            self._pending = None
            self._interrupt_locked()
            self._audio_clock_start = None
            self._play_requested_at = None
            self._wake.notify_all()

    def close(self):
        with self._wake:
            self._closed = True
            self._pending = None
            self._interrupt_locked()
            self._audio_clock_start = None
            self._wake.notify_all()
            worker = self._worker
        # On editor close (not ordinary seek), give the *owning worker* time to
        # finish native cleanup before the Windows Python process can exit.
        # Joining releases the lock and never closes the stream cross-thread.
        if worker and worker is not threading.current_thread():
            worker.join(timeout=2)
        if worker and worker.is_alive():
            self.errors.put('Audio device is still closing. '
                            'Keep Pulse Capture open briefly before exiting.')

    def _run(self):
        while True:
            with self._wake:
                self._wake.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                request = self._pending
                self._pending = None
                cancel = threading.Event()
                self._active_cancel = cancel
            self._run_session(cancel, *request)
            with self._wake:
                if self._active_cancel is cancel:
                    self._active_cancel = None
                if self._closed:
                    return

    def _run_session(self, cancel, position, trim, cuts, edits):
        process = stream = manager = None
        try:
            if cancel.is_set():
                return
            try:
                import pyaudiowpatch as pyaudio
            except (ImportError, OSError) as exc:
                raise RuntimeError('Install editor audio playback: '
                                   'python -m pip install -r requirements-audio.txt') from exc
            command = audio_preview_command(self.ffmpeg, self.media, position, trim,
                                            cuts, edits)
            if command is None or cancel.is_set():
                return
            manager = pyaudio.PyAudio()
            if cancel.is_set():
                return
            # Only this worker may open, write, stop, close and terminate
            # PortAudio; even a rapid seek cannot run two streams concurrently.
            stream = manager.open(format=pyaudio.paInt16, channels=2,
                                  rate=SAMPLE_RATE, output=True,
                                  frames_per_buffer=BLOCK_BYTES // 4)
            if cancel.is_set():
                return
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       **process_options())
            with self._lock:
                self._process = process
                if cancel.is_set():
                    process.terminate()
                    return
            while not cancel.is_set():
                data = process.stdout.read(BLOCK_BYTES)
                if not data or cancel.is_set():
                    break
                with self._lock:
                    if self._active_cancel is cancel and self._audio_clock_start is None:
                        self._audio_clock_start = time.monotonic()
                # Never hold the shared lock while the native device writes.
                stream.write(data)
            if not cancel.is_set():
                code = process.wait(timeout=2)
                if code:
                    raise RuntimeError('Editor audio decoding failed. '
                                       'Check source or music file.')
        except Exception as exc:
            if not cancel.is_set():
                with self._lock:
                    if self._active_cancel is cancel:
                        self._audio_failed = True
                self.errors.put(str(exc))
        finally:
            if process:
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
            # Never touch the stream or its manager outside this worker.
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if manager:
                try:
                    manager.terminate()
                except Exception:
                    pass
            with self._lock:
                if self._process is process:
                    self._process = None
