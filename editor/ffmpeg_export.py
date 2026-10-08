"""Pure trim/crop/branding command construction, separate from recording."""
from pathlib import Path
from branding import watermark_path
from .transforms import EditOptions, video_filters


def build_export_command(ffmpeg, media, trim, output, edits=None, asset=None):
    trim.validate(media)
    edits = edits or EditOptions()
    if Path(output).resolve() == media.path.resolve():
        raise ValueError('An export must use a different filename from the original.')
    asset = watermark_path() if asset is None else asset
    filters, complex_graph = video_filters(media, edits, asset)
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'warning', '-nostdin', '-n',
            '-stats_period', '0.25', '-progress', 'pipe:1',
            '-ss', f'{trim.start:.6f}', '-i', str(media.path)]
    if complex_graph:
        args += ['-i', str(asset)]
    args += ['-t', f'{trim.duration:.6f}']
    if complex_graph:
        args += ['-filter_complex', filters, '-map', '[v]']
    else:
        args += ['-vf', filters, '-map', '0:v:0']
    if media.has_audio:
        args += ['-map', '0:a:0', '-c:a', 'aac', '-b:a', '192k']
    else:
        args += ['-an']
    args += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
             '-map_metadata', '-1', '-movflags', '+faststart', '-f', 'mp4', str(output)]
    return args
