"""Pure trim/crop/branding command construction, separate from recording."""
from pathlib import Path
from branding import watermark_path
from .transforms import EditOptions, video_filters
from .polish import fade_seconds


def build_export_command(ffmpeg, media, trim, output, edits=None, asset=None, text_resources=None):
    trim.validate(media)
    edits = edits or EditOptions()
    edits.validate(media)
    if Path(output).resolve() == media.path.resolve():
        raise ValueError('An export must use a different filename from the original.')
    asset = watermark_path() if asset is None else asset
    filters, complex_graph = video_filters(media, edits, asset, text_resources, trim.duration)
    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'warning', '-nostdin', '-n',
            '-stats_period', '0.25', '-progress', 'pipe:1',
            '-ss', f'{trim.start:.6f}', '-t', f'{trim.duration:.6f}', '-i', str(media.path)]
    if edits.branding.enabled:
        args += ['-i', str(asset)]
    if complex_graph:
        args += ['-filter_complex', filters, '-map', '[v]']
    else:
        args += ['-vf', filters, '-map', '0:v:0']
    if media.has_audio:
        audio_filters = []
        if edits.speed != 1.0:
            audio_filters.append(f'atempo={edits.speed:g}')
        out_duration = edits.output_duration(trim.duration)
        fade = fade_seconds(out_duration)
        if edits.fade.fade_in:
            audio_filters.append(f'afade=t=in:st=0:d={fade:.6f}')
        if edits.fade.fade_out:
            audio_filters.append(f'afade=t=out:st={max(0, out_duration-fade):.6f}:d={fade:.6f}')
        args += ['-map', '0:a:0']
        if audio_filters:
            args += ['-af', ','.join(audio_filters)]
        args += ['-c:a', 'aac', '-b:a', '192k']
    else:
        args += ['-an']
    args += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
             '-map_metadata', '-1', '-movflags', '+faststart', '-f', 'mp4', str(output)]
    return args
