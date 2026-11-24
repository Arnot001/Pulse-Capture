"""Latest-request-wins, bounded-size silent frame previews. No Tk calls in workers."""
from dataclasses import dataclass
from queue import Queue, Full, Empty
import subprocess
import threading
import time
from capture.ffmpeg_backend import process_options
from branding import watermark_path
from .cuts import CutPlan
from .transforms import EditOptions, video_filters
from .models import TrimRange
from .text_overlay import TextResources


@dataclass(frozen=True)
class Frame:
    token: int
    position: float
    ppm: bytes = b''
    error: str = ''
    source_view: bool = True
    edits: EditOptions | None = None
    render_seconds: float = 0.0


def anticipated_source_position(cuts, trim, source_elapsed, speed, render_seconds):
    """Predict picture time when a decoded preview frame will reach the canvas.

    A single frame requires a fresh FFmpeg decode. If we ask for the exact
    *current* audio time, that picture is already old when it gets displayed.
    Work in the cut-aware output timeline so jumps and playback speeds remain
    correct. This affects preview only; export timestamps are untouched.
    """
    if not (0 < speed <= 16):
        raise ValueError('Invalid preview speed.')
    latency = min(3.0, max(0.0, float(render_seconds)))
    return cuts.source_from_elapsed(source_elapsed + speed * latency, trim)


def preview_command(ffmpeg, media, position, width, height, edits=None, source_view=True, text_resources=None, trim=None, cuts=None):
    width, height = max(2, min(1280, int(width))), max(2, min(720, int(height)))
    # Decode the last available frame at EOF, but keep the requested animation
    # time so scrubbing to trim end reaches the exact target zoom.
    animation_position = max(0, min(position, media.duration))
    position = max(0, min(position, max(0, media.duration - 1 / media.fps)))
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin',
            '-ss', f'{position:.6f}', '-i', str(media.path)]
    scale = f'scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1'
    if source_view:
        args += ['-map', '0:v:0', '-vf', scale]
    else:
        edits = edits or EditOptions()
        edits.validate(media)
        trim = trim or TrimRange(0, media.duration)
        trim.validate(media)
        cuts = cuts or CutPlan()
        cuts.validate_selection(media, trim)
        kept_duration = cuts.kept_duration(trim)
        output_time = cuts.source_elapsed(animation_position, trim) / edits.speed
        filters, complex_graph = video_filters(media, edits, watermark_path(), text_resources,
                                                kept_duration, output_time, trim=trim, cuts=cuts, source_position=position)
        if edits.branding.enabled:
            args += ['-i', str(watermark_path())]
        if edits.overlays:
            from .reactions import add_visuals
            graph = [filters] if complex_graph else [f'[0:v:0]{filters}[v]']
            out_w, out_h = edits.encoded_size(media)
            visual = add_visuals(args, graph, 'v', edits.overlays, out_w, out_h, output_time, edits.bands(media))
            graph.append(f'[{visual}]null[reactionpreview]')
            filters = ';'.join(graph)
            args += ['-filter_complex_threads', '1', '-filter_complex',
                     filters + f';[reactionpreview]{scale}[preview]', '-map', '[preview]']
        elif complex_graph:
            args += ['-filter_complex',
                     filters + f';[v]{scale}[preview]', '-map', '[preview]']
        else:
            args += ['-map', '0:v:0', '-vf', filters + ',' + scale]
    return args + ['-frames:v', '1', '-an', '-c:v', 'ppm', '-f', 'image2pipe', 'pipe:1']


class Preview:
    def __init__(self, ffmpeg, media):
        self.ffmpeg, self.media = ffmpeg, media
        self.frames = Queue(maxsize=1)
        self._condition = threading.Condition()
        self._pending = self._process = None
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def request(self, token, position, width, height, edits=None, source_view=True, trim=None, cuts=None):
        with self._condition:
            if not self._closed:
                self._pending = (token, position, width, height, edits, source_view, trim, cuts)
                if self._process is not None and self._process.poll() is None:
                    try:self._process.terminate()
                    except OSError:pass
                self._condition.notify()

    def close(self):
        with self._condition:
            self._closed = True
            if self._process and self._process.poll() is None:
                self._process.terminate()
            self._condition.notify()

    def _run(self):
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._pending is not None)
                if self._closed:
                    return
                token, position, width, height, edits, source_view, trim, cuts = self._pending
                self._pending = None
            process = resources = None
            request_started = time.monotonic()
            try:
                if not source_view:
                    resources = TextResources((edits or EditOptions()).text)
                command = preview_command(self.ffmpeg, self.media, position, width, height, edits, source_view, resources, trim, cuts)
                with self._condition:
                    if self._closed:
                        return
                    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                               stderr=subprocess.PIPE, **process_options())
                    self._process = process
                try:
                    data, error = process.communicate(timeout=12)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise RuntimeError('Preview took too long. Try another point in the video.')
                if process.returncode or not data.startswith(b'P6'):
                    raise RuntimeError('Could not load this preview frame. ' + error.decode('utf-8', 'replace')[-300:])
                frame = Frame(token, position, data, source_view=source_view,
                              edits=edits,
                              render_seconds=time.monotonic() - request_started)
            except Exception as exc:
                frame = Frame(token, position, error=str(exc))
            finally:
                try:
                    if resources:
                        resources.close()
                except OSError as exc:
                    frame = Frame(token, position, error=f'Could not remove temporary preview text: {exc}')
                with self._condition:
                    self._process = None
            if self._closed:
                return
            try:
                self.frames.put_nowait(frame)
            except Full:
                try:
                    self.frames.get_nowait()
                except Empty:
                    pass
                self.frames.put_nowait(frame)
