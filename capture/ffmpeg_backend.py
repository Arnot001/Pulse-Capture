"""Binary discovery, pure command construction, and output validation."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from .models import CaptureOptions


def process_options():
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def run(args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                          errors='replace', timeout=timeout, **process_options())


@dataclass(frozen=True)
class Backend:
    ffmpeg: str
    ffprobe: str
    audio_supported: bool


def discover():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    explicit = os.environ.get('PULSE_FFMPEG')
    ffmpeg = explicit or next((str(p) for p in (base / 'vendor' / 'ffmpeg.exe',
                            Path(sys.executable).parent / 'ffmpeg.exe') if p.is_file()), None)
    ffmpeg = ffmpeg or shutil.which('ffmpeg')
    if not ffmpeg or not Path(ffmpeg).is_file():
        raise RuntimeError('FFmpeg was not found. Install a Windows FFmpeg build or place it in vendor/.')
    probe = Path(ffmpeg).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    ffprobe = os.environ.get('PULSE_FFPROBE') or (str(probe) if probe.is_file() else shutil.which('ffprobe'))
    if not ffprobe or not Path(ffprobe).is_file():
        raise RuntimeError('FFprobe was not found. Install it alongside FFmpeg.')
    devices = run([ffmpeg, '-hide_banner', '-devices'])
    encoders = run([ffmpeg, '-hide_banner', '-encoders'])
    if devices.returncode or encoders.returncode:
        raise RuntimeError('FFmpeg could not report its capture capabilities.')
    if not re.search(r'\bD\s+gdigrab\b', devices.stdout + devices.stderr):
        raise RuntimeError('This FFmpeg build does not support Windows gdigrab capture.')
    if not re.search(r'\blibx264\b', encoders.stdout):
        raise RuntimeError('This FFmpeg build needs the libx264 encoder.')
    if run([ffprobe, '-version']).returncode:
        raise RuntimeError('FFprobe could not be started.')
    return Backend(ffmpeg, ffprobe, bool(re.search(r'\bD\s+dshow\b', devices.stdout + devices.stderr)))


def build_command(ffmpeg, options: CaptureOptions, output):
    options.validate()
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'warning', '-n',
            '-stats_period', '0.25', '-progress', 'pipe:1', '-thread_queue_size', '512',
            '-f', 'gdigrab', '-framerate', str(options.fps), '-draw_mouse', '1']
    if options.mode == 'region':
        r = options.region
        args += ['-offset_x', str(r.x), '-offset_y', str(r.y), '-video_size', f'{r.width}x{r.height}']
    target = f'hwnd={options.hwnd}' if options.mode == 'window' else 'desktop'
    args += ['-i', target]
    for device in options.audio:
        args += ['-thread_queue_size', '512', '-f', 'dshow', '-audio_buffer_size', '50',
                 '-i', f'audio={device}']
    args += ['-map', '0:v:0']
    if len(options.audio) == 2:
        args += ['-filter_complex',
                 '[1:a]aresample=async=1:first_pts=0[a1];'
                 '[2:a]aresample=async=1:first_pts=0[a2];'
                 '[a1][a2]amix=inputs=2:duration=longest:dropout_transition=2:normalize=1[a]',
                 '-map', '[a]']
    elif options.audio:
        args += ['-map', '1:a:0', '-af', 'aresample=async=1:first_pts=0']
    else:
        args += ['-an']
    args += ['-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-c:v', 'libx264',
             '-preset', 'veryfast', '-crf', '23' if options.quality == 'Standard' else '18',
             '-pix_fmt', 'yuv420p', '-r', str(options.fps)]
    if options.audio:
        args += ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2']
    return args + ['-movflags', '+faststart', '-f', 'mp4', str(output)]


def validate_output(ffprobe, path, expect_audio=False):
    path = Path(path)
    if not path.is_file() or path.stat().st_size < 128:
        raise RuntimeError('FFmpeg did not produce a usable recording.')
    result = run([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], 30)
    if result.returncode:
        raise RuntimeError('The recording failed validation: ' + result.stderr[-1000:])
    info = json.loads(result.stdout)
    streams = info.get('streams', [])
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    if not video or int(video.get('nb_frames', 0)) < 1 or float(info.get('format', {}).get('duration', 0)) <= 0:
        raise RuntimeError('The recording contains no completed video frames.')
    if expect_audio and not any(s.get('codec_type') == 'audio' for s in streams):
        raise RuntimeError('The requested audio track is missing.')
    return info
