"""Bounded local FFmpeg analysis; no uploads, external packages or source writes."""
from array import array
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

from capture.ffmpeg_backend import process_options
from .auto_plan import validate_plan

ANALYSIS_VERSION = 1
MAX_FRAMES = 1200
THUMBNAILS = 18


class AutoCancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise AutoCancelled('Auto Edit cancelled. Original footage is unchanged.')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     suffix='.tmp', delete=False) as file:
        temp = Path(file.name)
        try:
            json.dump(value, file, ensure_ascii=False, indent=2, allow_nan=False)
            file.flush()
            import os
            os.fsync(file.fileno())
        except Exception:
            file.close()
            temp.unlink(missing_ok=True)
            raise
    try:
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def fingerprint(path, cancel):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        while data := source.read(4*1024*1024):
            check_cancel(cancel)
            digest.update(data)
    return digest.hexdigest()


def run_local(command, cancel, timeout=600):
    """Spool bounded scan data to disk, keeping cancellation responsive."""
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=errors, **process_options())
        try:
            deadline = time.monotonic()+timeout
            while process.poll() is None:
                check_cancel(cancel)
                if time.monotonic() > deadline:
                    raise RuntimeError('Local analysis timed out. Try a shorter source.')
                cancel.wait(.1)
            check_cancel(cancel)
            if process.returncode:
                errors.seek(0)
                raise RuntimeError('Local video analysis failed: ' + errors.read()[-600:].decode('utf-8', 'replace'))
            output.seek(0)
            return output.read()
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(3)


def read_transcript(source, duration):
    """An explicitly accompanying SRT is trusted only as transcript, never instruction."""
    path = Path(source).with_suffix('.srt')
    if not path.exists():
        return [], 'No speech transcript found. Add a matching .srt for speech captions.'
    if path.stat().st_size > 2_000_000:
        raise ValueError('Transcript is too large (maximum 2 MB).')
    text = path.read_text(encoding='utf-8-sig')
    pattern = re.compile(r'(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})[^\n]*\n(.*?)(?=\n\s*\n|\Z)', re.S)
    def seconds(value):
        h, m, s = value.replace(',', '.').split(':')
        if int(m) >= 60 or float(s) >= 60:
            raise ValueError('Invalid SRT timestamp.')
        return int(h)*3600+int(m)*60+float(s)
    result = []
    for match in pattern.finditer(text.replace('\r\n', '\n')):
        start, end = seconds(match[1]), seconds(match[2])
        words = re.sub(r'<[^>]*>', '', match[3]).split()
        if not 0 <= start < end <= duration+.1 or not words:
            raise ValueError('Transcript cues must lie inside the source video.')
        # Split long speech into short, readable chunks with proportional timing.
        groups, group = [], []
        for word in words:
            if len(word) > 60:
                raise ValueError('Shorten very long transcript words.')
            if len(' '.join(group+[word])) > 60 and group:
                groups.append(' '.join(group))
                group = []
            group.append(word)
        groups.append(' '.join(group))
        for index, phrase in enumerate(groups):
            result.append({'start': start+(end-start)*index/len(groups),
                           'end': min(duration, start+(end-start)*(index+1)/len(groups)), 'text': phrase})
    if not result:
        raise ValueError('No valid SRT cues were found.')
    if len(result) > 6000:
        raise ValueError('Transcript has too many cues.')
    return result, 'Speech captions from the matching local SRT; review transcript accuracy.'


def analyse(backend, media, cache_root, cancel, progress=lambda message: None):
    if media.duration > 7200:
        raise ValueError('For this first version, use source videos up to two hours.')
    progress('Checking source fingerprint and reusable analysis…')
    digest = fingerprint(media.path, cancel)
    folder = Path(cache_root) / f'analysis-v{ANALYSIS_VERSION}' / digest
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'analysis.json'
    if path.exists():
        try:
            cached = json.loads(path.read_text(encoding='utf-8'))
            if cached['digest'] == digest and all((folder/f['file']).is_file() for f in cached['frames']):
                progress('Reusing local scene analysis.')
                return cached, folder
        except (ValueError, KeyError, TypeError):
            pass
    step = max(.5, media.duration/MAX_FRAMES)
    width, height = 160, 90
    progress('Scanning scene changes and visual activity…')
    common = [str(backend.ffmpeg), '-hide_banner', '-v', 'error', '-nostdin', '-i', str(media.path)]
    raw = run_local(common+['-map', '0:v:0', '-vf', f'fps=1/{step:.9f},scale={width}:{height}',
                           '-frames:v', str(MAX_FRAMES), '-pix_fmt', 'gray', '-an', '-f', 'rawvideo', 'pipe:1'], cancel)
    frame_size = width*height
    samples, previous, previous_hist = [], None, None
    for index in range(len(raw)//frame_size):
        check_cancel(cancel)
        frame = raw[index*frame_size:(index+1)*frame_size]
        histogram = [0]*16
        for pixel in frame:
            histogram[pixel//16] += 1
        if previous is None:
            motion, scene, focus = 0, 0, .5
        else:
            columns = [0]*width
            delta = 0
            for pixel, (a, b) in enumerate(zip(frame, previous)):
                diff = abs(a-b)
                delta += diff
                columns[pixel % width] += max(0, diff-12)
            motion = delta / frame_size / 255
            scene = sum(abs(a-b) for a, b in zip(histogram, previous_hist))/frame_size/2
            weight = sum(columns)
            focus = sum((x+.5)*v for x, v in enumerate(columns))/weight/width if weight else .5
            # Camera cuts and whole-frame motion aren't reliable subject trackers.
            if scene > .25:
                focus = .5
        brightness = sum(frame)/frame_size/255
        samples.append({'time': round(min(media.duration, index*step), 3),
                        'motion': round(motion, 4), 'scene': round(scene, 4),
                        'brightness': round(brightness, 4), 'focus_x': round(focus, 4), 'audio': 0.0})
        previous, previous_hist = frame, histogram
    del raw
    if not samples:
        raise ValueError('No usable frames found in this source.')
    if media.has_audio:
        progress('Measuring audio activity; silent scenes remain eligible…')
        # 1000 samples/second suffice for activity, with a bounded 28.8 MB at 2 h.
        raw = run_local(common+['-map', '0:a:0', '-vn', '-ac', '1', '-ar', '1000',
                                '-f', 'f32le', 'pipe:1'], cancel)
        audio = array('f')
        audio.frombytes(raw[:len(raw)//4*4])
        if sys.byteorder != 'little':
            audio.byteswap()
        for sample in samples:
            check_cancel(cancel)
            chunk = audio[int(sample['time']*1000):int((sample['time']+step)*1000)]
            if chunk:
                rms = math.sqrt(sum(x*x for x in chunk)/len(chunk))
                sample['audio'] = round(min(1, max(0, (20*math.log10(max(rms, 1e-8))+60)/60)), 4)
    progress('Extracting a small, time-distributed set of scene thumbnails…')
    frames = []
    # One useful sample per time bucket guarantees coverage instead of only loud moments.
    for index in range(min(THUMBNAILS, len(samples))):
        group = samples[index*len(samples)//THUMBNAILS:(index+1)*len(samples)//THUMBNAILS] if len(samples) >= THUMBNAILS else [samples[index]]
        candidate = max(group, key=lambda s: (.5*s['scene']+s['motion']) if s['brightness'] > .035 else -1)
        at = min(media.duration-1/media.fps, candidate['time']+min(.2, step/2))
        filename = f'frame-{index:02d}.jpg'
        run_local([str(backend.ffmpeg), '-v', 'error', '-nostdin', '-y', '-ss', f'{at:.6f}',
                   '-i', str(media.path), '-frames:v', '1', '-vf',
                   'scale=512:512:force_original_aspect_ratio=decrease', '-q:v', '3', str(folder/filename)], cancel, 30)
        frames.append({'time': round(at, 3), 'file': filename})
    result = {'digest': digest, 'duration': media.duration, 'step': step, 'samples': samples,
              'scenes': [s['time'] for s in samples if s['scene'] >= .25], 'frames': frames,
              'method': 'sampled luminance changes + histogram cuts + RMS audio; motion is not semantic understanding'}
    atomic_json(path, result)
    return result, folder


def local_plan(analysis, media, options, transcript=()):
    """Choose distinct coherent windows with scene/speech-aware edges, not random cuts."""
    options.validate()
    if media.duration < options.minimum:
        raise ValueError('The source is shorter than your minimum duration. Lower the target or choose a longer video.')
    samples = analysis['samples']
    desired = (options.minimum+options.maximum)/2
    boundaries = sorted(set([0., media.duration]+analysis['scenes']+
                            [c[k] for c in transcript for k in ('start', 'end')]))
    starts = sorted(set([0.]+[b for b in boundaries if b <= media.duration-options.minimum]+
                        [float(x) for x in range(0, int(media.duration-options.minimum)+1, 3)]))
    candidates = []
    for start in starts:
        ends = [b for b in boundaries if options.minimum <= b-start <= options.maximum]
        end = min(ends, key=lambda b: abs(b-start-desired)) if ends else min(media.duration, start+desired)
        if end-start < options.minimum:
            continue
        window = [s for s in samples if start <= s['time'] < end]
        opening = [s for s in window if s['time'] < start+3]
        if not window or sum(s['brightness'] < .035 for s in window)/len(window) > .15:
            continue
        weight = {'Gaming': (2.5, .4), 'News/Preview': (1.4, .3), 'Funny Moments': (1.5, .7),
                  'Comedy / Roast': (1.5, .7)}[options.style]
        def activity(group):
            return sum(weight[0]*s['motion']+.5*s['scene']+weight[1]*s['audio'] for s in group)/max(1, len(group))
        score = activity(window)+.6*activity(opening)
        if start in boundaries:
            score += .08
        if any(c['start'] < start < c['end'] or c['start'] < end < c['end'] for c in transcript):
            score -= .25
        candidates.append((score, start, end, window))
    selected = []
    for score, start, end, window in sorted(candidates, reverse=True):
        if any(max(0, min(end, b)-max(start, a))/min(end-start, b-a) > .15 for a, b, _ in selected):
            continue
        selected.append((start, end, window))
        if len(selected) == options.count:
            break
    if not selected:
        raise ValueError('No suitable non-black sequence found. Review this footage manually.')
    shorts = []
    for index, (start, end, window) in enumerate(selected):
        # Adjacent ranges introduce crop keys, not extra cuts. Follow local motion
        # in short spans; scene-boundary resets avoid panning across hard cuts.
        edges = sorted(set([start, end]+[s for s in analysis['scenes'] if start+1 < s < end-1]))
        # Merge nearby scene boundaries to prevent sub-second shots.
        safe_edges = [edges[0]]
        for marker in edges[1:-1]:
            if marker - safe_edges[-1] >= 1.05 and end - marker >= 1.05:
                safe_edges.append(marker)
        edges = safe_edges + [edges[-1]]
        if len(edges) > 9:
            edges = [start, end]
        while len(edges) < 9:
            a, b = max(zip(edges, edges[1:]), key=lambda pair: pair[1]-pair[0])
            if b-a <= 5:
                break
            edges.append((a+b)/2)
            edges.sort()
        shots = []
        for a, b in zip(edges, edges[1:]):
            def focus(at):
                near = sorted(window, key=lambda s: abs(s['time']-at))[:3]
                return sorted(s['focus_x'] for s in near)[len(near)//2]
            shots.append({'start': a, 'end': b, 'focus_x': focus(a+.3), 'focus_y': .5,
                          'end_focus_x': focus(b-.3), 'end_focus_y': .5})
        title = f'{options.style} · selection {index+1}'
        shorts.append({'title': title, 'description': 'Local-only candidate. Review footage and add a specific title before publishing.',
                       'rationale': 'Distinct continuous sequence ranked by visual activity, opening energy and natural boundaries. '
                                    'Local scoring cannot understand humour or verify news claims.',
                       'verification': ['Review the crop, opening hook and all factual claims.'],
                       'shots': shots, 'captions': []})
    return validate_plan({'shorts': shorts}, media, options)
