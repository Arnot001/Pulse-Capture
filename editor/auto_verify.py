"""Full decode and format checks before publishing an Auto Edit export."""
import json
from pathlib import Path

from .auto_analysis import run_local


def verify_short(backend, path, expected_duration, expect_audio, cancel):
    info = json.loads(run_local([str(backend.ffprobe), '-v', 'error', '-show_streams',
                                '-show_format', '-of', 'json', str(path)], cancel, 30))
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    if (video['width'], video['height']) != (1080, 1920) or video['codec_name'] != 'h264':
        raise ValueError('Auto Edit export must be 1080 × 1920 H.264.')
    duration = float(info['format']['duration'])
    if abs(duration-expected_duration) > .15:
        raise ValueError('Auto Edit export duration differs from the plan.')
    audio = next((s for s in info['streams'] if s['codec_type'] == 'audio'), None)
    if expect_audio:
        if not audio or audio['codec_name'] != 'aac':
            raise ValueError('The source audio was not preserved as AAC.')
        if abs(float(audio.get('start_time', 0))-float(video.get('start_time', 0))) > .1:
            raise ValueError('Audio and video start times differ.')
        if abs(float(audio.get('duration', duration))-float(video.get('duration', duration))) > .15:
            raise ValueError('Audio and video lengths differ.')
    run_local([str(backend.ffmpeg), '-v', 'error', '-nostdin', '-xerror', '-err_detect', 'explode',
               '-i', str(path), '-map', '0:v:0', '-map', '0:a:0?', '-f', 'null', '-'], cancel, 240)
    # Detect sustained black runs; use metadata on stdout, never parse arbitrary stderr.
    black = run_local([str(backend.ffmpeg), '-v', 'error', '-nostdin', '-i', str(path), '-an',
                       '-vf', 'scale=160:284,blackdetect=d=0.15:pix_th=0.10:pic_th=0.98,metadata=mode=print:file=-',
                       '-f', 'null', '-'], cancel, 240).decode('utf-8', 'replace')
    starts, ends = [], []
    for line in black.splitlines():
        if line.startswith('lavfi.black_start='):
            starts.append(float(line.split('=', 1)[1]))
        if line.startswith('lavfi.black_end='):
            ends.append(float(line.split('=', 1)[1]))
    # Black pixels can be intentional: scene cuts, comic pauses, fades and dark
    # gameplay are valid content. Only decode/format/audio-integrity errors
    # should prevent publishing. Report black spans for manual review instead
    # of discarding the finished MP4.
    black_intervals = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else duration
        if end - start >= .15:
            black_intervals.append((round(start, 3), round(min(end, duration), 3)))
    return {'path': str(Path(path)), 'width': 1080, 'height': 1920, 'duration': duration,
            'video_codec': 'h264', 'audio_codec': audio['codec_name'] if audio else None,
            'full_decode': True, 'sustained_black_frames': bool(black_intervals),
            'black_intervals': black_intervals}
