"""Pure trim command construction. Recorder options are deliberately separate."""
from pathlib import Path


def build_export_command(ffmpeg, media, trim, output):
    trim.validate(media)
    if Path(output).resolve() == media.path.resolve():
        raise ValueError('An export must use a different filename from the original.')
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'warning', '-nostdin', '-n',
            '-stats_period', '0.25', '-progress', 'pipe:1',
            '-ss', f'{trim.start:.6f}', '-i', str(media.path),
            '-t', f'{trim.duration:.6f}', '-map', '0:v:0']
    if media.has_audio:
        args += ['-map', '0:a:0', '-c:a', 'aac', '-b:a', '192k']
    else:
        args += ['-an']
    # Re-encoding makes cuts accurate between keyframes. Burned-in branding stays.
    args += ['-vf', 'pad=ceil(iw/2)*2:ceil(ih/2)*2', '-c:v', 'libx264',
             '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
             '-map_metadata', '-1', '-movflags', '+faststart', '-f', 'mp4', str(output)]
    return args
