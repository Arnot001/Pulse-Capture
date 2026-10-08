"""Read local video metadata using the existing FFprobe executable."""
from fractions import Fraction
import json
from pathlib import Path
from capture.ffmpeg_backend import run
from .models import MediaInfo


def probe_media(ffprobe, path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('This recording has moved or was deleted. Open its folder to check.')
    result = run([str(ffprobe), '-v', 'error', '-show_streams', '-show_format',
                  '-of', 'json', str(path)], timeout=20)
    if result.returncode:
        raise ValueError('This video could not be opened. ' + result.stderr[-500:])
    try:
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        video = next(s for s in streams if s.get('codec_type') == 'video'
                     and not s.get('disposition', {}).get('attached_pic'))
        rate = video.get('avg_frame_rate') or video.get('r_frame_rate')
        duration = video.get('duration') or data.get('format', {}).get('duration')
        media = MediaInfo(path, float(duration), int(video['width']), int(video['height']),
                          float(Fraction(rate)), any(s.get('codec_type') == 'audio' for s in streams))
        media.validate()
        return media
    except (ValueError, TypeError, KeyError, StopIteration, ZeroDivisionError) as exc:
        raise ValueError('This file does not contain a usable video track.') from exc
