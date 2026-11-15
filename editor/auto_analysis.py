"""Bounded on-device scene/audio analysis using Pulse's existing FFmpeg.

This is not semantic AI transcription. It produces reviewable moments locally.
Nothing is uploaded; the source recording is never modified.
"""
import re
import subprocess
import time

from capture.ffmpeg_backend import process_options
from .auto_plan import choose_highlights

SCENE_TIME = re.compile(r'\bpts_time:([0-9]+(?:\.[0-9]+)?)')
ENERGY_LEVEL = re.compile(r'lavfi\.astats\.Overall\.RMS_level=([-+]?(?:\d+(?:\.\d+)?|inf|nan))')
ANALYSIS_LIMIT = 600.0


def parse_scene_log(log):
    """showinfo runs only on frames that crossed the visual change threshold."""
    return tuple(float(m.group(1)) for line in log.splitlines()
                 if 'showinfo' in line for m in SCENE_TIME.finditer(line))


def parse_energy_log(log):
    """Read per-second RMS dBFS, retaining source timestamps."""
    position = None
    result = []
    for line in log.splitlines():
        if 'pts_time:' in line and 'frame:' in line:
            m = SCENE_TIME.search(line)
            if m:
                position = float(m.group(1))
        elif position is not None:
            m = ENERGY_LEVEL.search(line)
            if m:
                try:
                    db = float(m.group(1))
                    if db == float('-inf'):
                        db = -90.0
                    if -1000.0 < db < 1000.0:
                        result.append((position, db))
                except ValueError:
                    pass
                position = None
    return tuple(result)


def _scan(ffmpeg, media, filters, *, kind, seconds, cancel_event=None):
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'info', '-nostdin',
            '-i', str(media.path), '-t', f'{seconds:.3f}']
    if kind == 'video':
        args += ['-vf', filters, '-an']
    else:
        args += ['-af', filters, '-vn']
    args += ['-f', 'null', '-']
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace',
                               **process_options())
    try:
        deadline = time.monotonic() + 150
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError('Auto scan cancelled.')
            if time.monotonic() > deadline:
                raise RuntimeError('Auto scan took too long. Try a shorter recording.')
            try:
                _, log = process.communicate(timeout=1)
                break
            except subprocess.TimeoutExpired:
                pass
        if process.returncode:
            raise RuntimeError(f'Auto {kind} analysis failed: {log[-500:]}')
        return log
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def analyze_video(ffmpeg, media, *, style='Gaming', count=1, cancel_event=None):
    """Return (suggestions, explanation) based on the original source timeline."""
    media.validate()
    seconds = min(media.duration, ANALYSIS_LIMIT)
    visual = _scan(ffmpeg, media,
                   "fps=2,scale=160:-2,select='gt(scene,0.30)',showinfo",
                   kind='video', seconds=seconds, cancel_event=cancel_event)
    scenes = parse_scene_log(visual)
    energy = ()
    if media.has_audio:
        audio = _scan(ffmpeg, media,
                      'aresample=8000,asetnsamples=n=8000:p=1,'
                      'astats=metadata=1:reset=1,'
                      'ametadata=print:key=lavfi.astats.Overall.RMS_level',
                      kind='audio', seconds=seconds, cancel_event=cancel_event)
        energy = parse_energy_log(audio)
    candidates = choose_highlights(seconds, scenes, energy, style=style, count=count)
    info = f'Analyzed {seconds:.0f}s · {len(scenes)} scene changes · {len(energy)} audio samples'
    if media.duration > ANALYSIS_LIMIT:
        info += ' · First 10 minutes only'
    return candidates, info
