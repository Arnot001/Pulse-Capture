"""Combine temporary Windows playback audio with the recorded MP4.

The existing microphone stays in FFmpeg's source MP4. A mixed AAC track is
published only after a validated, successful merge; the source video is copied.
"""
from pathlib import Path
import subprocess
from .ffmpeg_backend import process_options


def merge_command(ffmpeg, video, wav, destination, duration, microphone, offset=0.0):
    if duration <= 0:
        raise ValueError('Video duration must be positive.')
    if Path(video).resolve() == Path(destination).resolve():
        raise ValueError('Cannot merge over an unvalidated recording.')
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
            '-i', str(video)]
    # If loopback began before video startup, discard its pre-roll; if the
    # loopback started late, add silence before it to align with video.
    if offset > 0:
        args += ['-ss', f'{offset:.6f}']
    elif offset < 0:
        args += ['-itsoffset', f'{-offset:.6f}']
    args += ['-i', str(wav)]
    if microphone:
        args += ['-filter_complex',
                 '[0:a:0]aresample=async=1:first_pts=0[mic];'
                 '[1:a:0]aresample=async=1:first_pts=0[desktop];'
                 '[mic][desktop]amix=inputs=2:duration=longest:'
                 'dropout_transition=0:normalize=1[a]']
    args += ['-map', '0:v:0', '-map', '[a]' if microphone else '1:a:0',
             '-t', f'{duration:.6f}', '-c:v', 'copy',
             '-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2',
             '-movflags', '+faststart', '-f', 'mp4', str(destination)]
    return args


def merge_audio(ffmpeg, video, wav, destination, duration, microphone, offset=0.0):
    command = merge_command(ffmpeg, video, wav, destination, duration, microphone, offset)
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                            text=True, encoding='utf-8', errors='replace',
                            **process_options())
    if result.returncode:
        raise RuntimeError('Could not combine Windows audio with your video: ' +
                           result.stderr[-1000:])
