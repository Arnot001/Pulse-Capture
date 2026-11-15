"""Combine temporary Windows playback audio with the recorded MP4.

The existing microphone stays in FFmpeg's source MP4. A mixed AAC track is
published only after a validated, successful merge; the source video is copied.
"""
from pathlib import Path
import math
import subprocess
from .ffmpeg_backend import process_options


def measured_sync_offset(audio_duration, video_duration):
    """Align WASAPI and video by their common stop rather than FFmpeg startup.

    We start WASAPI before launching gdigrab, but FFmpeg's first progress
    callback is delayed by encoding. Guessing the first frame's wall-clock
    time from that callback over-trimmed playback by about 0.9 seconds in
    actual captures. Both devices receive Stop together, so their *recorded
    durations* give the amount of earlier audio pre-roll to discard.

    Positive: discard audio pre-roll. Negative: delay late-starting audio.
    Only accept plausible startup offsets; huge differences indicate a
    broken clock, not legitimate pre-roll.
    """
    try:
        audio_duration = float(audio_duration)
        video_duration = float(video_duration)
    except (ValueError, TypeError) as exc:
        raise RuntimeError('Cannot measure capture audio/video durations.') from exc
    if not all(math.isfinite(x) and x > 0 for x in (audio_duration, video_duration)):
        raise RuntimeError('Invalid audio/video duration while aligning capture.')
    offset = audio_duration - video_duration
    if abs(offset) > 8.0:
        raise RuntimeError(
            f'Windows audio and video durations differ by {abs(offset):.2f}s. '
            'The recording was not saved as synchronised.'
        )
    return offset


def merge_command(ffmpeg, video, wav, destination, duration, microphone, offset=0.0):
    """Return a filter-based, sample-timed A/V merge command.

    Do not use input -itsoffset for late-starting WAVs: FFmpeg can produce an
    AAC stream with start_time > 0 and duration < video duration, even though
    the audio finishes at the correct end timestamp. That broke validation
    and left users with a video-only .partial.mp4.

    Instead insert *real silent PCM samples* before late audio, or trim real
    samples from the beginning of early audio. Pad/trim the aligned soundtrack
    to the video timeline. This preserves the video bitstream without changes.
    """
    duration, offset = float(duration), float(offset)
    if not (math.isfinite(duration) and duration > 0):
        raise ValueError('Video duration must be positive and finite.')
    if not math.isfinite(offset):
        raise ValueError('Audio offset must be finite.')
    if Path(video).resolve() == Path(destination).resolve():
        raise ValueError('Cannot merge over an unvalidated recording.')

    length = f'{duration:.6f}'
    system_filters = []
    if offset > 0:
        # WAV started before the first captured picture: discard only pre-roll.
        system_filters.append(f'atrim=start={offset:.6f}')
    system_filters.append('asetpts=PTS-STARTPTS')
    if offset < 0:
        # WAV started after the picture: insert samples (rather than merely
        # moving timestamps with -itsoffset) to cover the missing start.
        system_filters.append(f'adelay=delays={round(-offset * 1000)}:all=1')
    system_filters.extend([
        'aresample=48000',
        f'apad=whole_dur={length}',
        f'atrim=duration={length}',
        'asetpts=PTS-STARTPTS',
    ])
    graph = [f'[1:a:0]{",".join(system_filters)}[desktop]']
    if microphone:
        graph.append(
            '[0:a:0]aresample=async=1:first_pts=0,'
            f'apad=whole_dur={length},atrim=duration={length},'
            'asetpts=PTS-STARTPTS[mic]'
        )
        graph.append(
            '[mic][desktop]amix=inputs=2:duration=longest:'
            'dropout_transition=0:normalize=1[a]'
        )
    else:
        graph.append('[desktop]anull[a]')

    return [
        str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
        '-i', str(video), '-i', str(wav),
        '-filter_complex', ';'.join(graph),
        '-map', '0:v:0', '-map', '[a]',
        '-t', length,
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-ar', '48000', '-ac', '2',
        '-movflags', '+faststart', '-f', 'mp4', str(destination),
    ]


def merge_audio(ffmpeg, video, wav, destination, duration, microphone, offset=0.0):
    command = merge_command(ffmpeg, video, wav, destination, duration, microphone, offset)
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding='utf-8', errors='replace',
                            **process_options())
    if result.returncode:
        raise RuntimeError('Could not combine Windows audio with your video: ' +
                           result.stderr[-1000:])
