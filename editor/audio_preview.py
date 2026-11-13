"""Audible Quick Edit preview: play source audio + music without rendering video.

FFmpeg decodes only the audio kept by Trim/Cut, applies clip speed and volumes,
and produces PCM. PyAudioWPatch sends that PCM to the current Windows output.
No audio is stored or uploaded. Video preview remains the existing frame worker.
"""
from queue import Queue
import subprocess
import threading

from capture.ffmpeg_backend import process_options
from .cuts import CutPlan
from .music import resolve_music_path
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
    if not media.has_audio and not edits.music.enabled:
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
        if edits.music.loop:
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
        music_filters = [
            f'atrim=start={output_offset:.9f}:end={output_offset+duration:.9f}',
            'asetpts=PTS-STARTPTS', f'volume={edits.music.music_volume:g}',
        ]
        if not edits.music.loop:
            music_filters.append(f'apad=pad_dur={duration:.9f}')
        graph.append(f'[1:a:0]{",".join(music_filters)}[music]')
    if media.has_audio and edits.music.enabled:
        graph.append('[source][music]amix=inputs=2:duration=longest:'
                     'dropout_transition=0:normalize=0,'
                     'alimiter=limit=0.95:level=false:latency=true[aout]')
    else:
        label = 'source' if media.has_audio else 'music'
        graph.append(f'[{label}]anull[aout]')
    args += ['-filter_complex', ';'.join(graph), '-map', '[aout]',
             '-t', f'{duration:.9f}', '-ac', '2', '-ar', str(SAMPLE_RATE),
             '-c:a', 'pcm_s16le', '-f', 's16le', 'pipe:1']
    return args


class AudioPlayback:
    """Background audio-only player. Never calls Tk from worker threads."""
    def __init__(self, ffmpeg, media):
        self.ffmpeg, self.media = ffmpeg, media
        self.errors = Queue()
        self._worker = self._process = self._stream = None
        self._closed = False
        self._cancel = threading.Event()
        self._lock = threading.RLock()

    def play(self, position, trim, cuts, edits):
        self.stop()
        if not self.media.has_audio and not edits.music.enabled:
            return
        with self._lock:
            if self._closed:
                return
            cancel = threading.Event()
            self._cancel = cancel
            self._worker = threading.Thread(
                target=self._run, args=(cancel, position, trim, cuts, edits),
                daemon=True, name='Pulse edit audio preview')
            self._worker.start()

    def stop(self):
        with self._lock:
            self._cancel.set()
            process = self._process
            stream = self._stream
            if process and process.poll() is None:
                try:
                    process.terminate()
                except OSError:
                    pass
            if stream:
                try:
                    stream.stop_stream()
                except Exception:
                    pass

    def close(self):
        self.stop()
        with self._lock:
            self._closed = True

    def _run(self, cancel, position, trim, cuts, edits):
        process = stream = manager = None
        try:
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
            stream = manager.open(format=pyaudio.paInt16, channels=2,
                                  rate=SAMPLE_RATE, output=True,
                                  frames_per_buffer=BLOCK_BYTES // 4)
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       **process_options())
            with self._lock:
                if cancel.is_set():
                    process.terminate()
                    return
                self._process, self._stream = process, stream
            while not cancel.is_set():
                data = process.stdout.read(BLOCK_BYTES)
                if not data:
                    break
                stream.write(data)
            if not cancel.is_set():
                code = process.wait(timeout=2)
                if code:
                    raise RuntimeError('Editor audio decoding failed. '
                                       'Check source or music file.')
        except Exception as exc:
            if not cancel.is_set():
                self.errors.put(str(exc))
        finally:
            if process:
                if process.poll() is None:
                    process.kill()
                try:
                    process.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
            if stream:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
            if manager:
                manager.terminate()
            with self._lock:
                if self._cancel is cancel:
                    self._process = self._stream = None
