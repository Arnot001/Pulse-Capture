"""Pure non-destructive edit/export command construction."""
from pathlib import Path
from branding import watermark_path
from .cuts import CutPlan
from .transforms import EditOptions, video_filters
from .polish import fade_seconds, audio_tempo_filters


def _cut_filter_graph(media, trim, cuts):
    """Build source-time trim/concat filters and return graph plus output labels."""
    segments = cuts.kept_segments(trim)
    if not segments:
        raise ValueError('Cuts would remove the entire selected video. Restore a section first.')

    graph = []
    video_labels, audio_labels = [], []
    for index, segment in enumerate(segments):
        video = f'cutv{index}'
        graph.append(
            f'[0:v:0]trim=start={segment.start:.9f}:end={segment.end:.9f},'
            f'setpts=PTS-STARTPTS[{video}]'
        )
        video_labels.append(video)
        if media.has_audio:
            audio = f'cuta{index}'
            graph.append(
                f'[0:a:0]atrim=start={segment.start:.9f}:end={segment.end:.9f},'
                f'asetpts=PTS-STARTPTS[{audio}]'
            )
            audio_labels.append(audio)

    if len(segments) == 1:
        return graph, video_labels[0], audio_labels[0] if media.has_audio else None

    if media.has_audio:
        joined = ''.join(f'[{v}][{a}]' for v, a in zip(video_labels, audio_labels))
        graph.append(f'{joined}concat=n={len(segments)}:v=1:a=1[cutv][cuta]')
        return graph, 'cutv', 'cuta'

    joined = ''.join(f'[{label}]' for label in video_labels)
    graph.append(f'{joined}concat=n={len(segments)}:v=1:a=0[cutv]')
    return graph, 'cutv', None


def build_export_command(ffmpeg, media, trim, output, edits=None, asset=None,
                         text_resources=None, cuts=None):
    trim.validate(media)
    edits = edits or EditOptions()
    edits.validate(media)
    cuts = cuts or CutPlan()
    cuts.validate_selection(media, trim)
    if Path(output).resolve() == media.path.resolve():
        raise ValueError('An export must use a different filename from the original.')

    asset = watermark_path() if asset is None else asset
    active_cuts = bool(cuts.visible_ranges(trim))
    kept_duration = cuts.kept_duration(trim)

    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'warning', '-nostdin', '-n',
            '-stats_period', '0.25', '-progress', 'pipe:1']
    if active_cuts:
        args += ['-i', str(media.path)]
    else:
        args += ['-ss', f'{trim.start:.6f}', '-t', f'{trim.duration:.6f}', '-i', str(media.path)]
    if edits.branding.enabled:
        args += ['-i', str(asset)]

    if active_cuts:
        graph, video_input, audio_input = _cut_filter_graph(media, trim, cuts)
        filters, complex_graph = video_filters(
            media, edits, asset, text_resources, kept_duration, input_label=video_input, trim=trim, cuts=cuts
        )
        if complex_graph:
            graph.append(filters)
        else:
            graph.append(f'[{video_input}]{filters}[v]')

        if media.has_audio:
            audio_filters = audio_tempo_filters(edits.speed)
            out_duration = edits.output_duration(kept_duration)
            fade = fade_seconds(out_duration)
            if edits.fade.fade_in:
                audio_filters.append(f'afade=t=in:st=0:d={fade:.6f}')
            if edits.fade.fade_out:
                audio_filters.append(
                    f'afade=t=out:st={max(0, out_duration-fade):.6f}:d={fade:.6f}'
                )
            if audio_filters:
                graph.append(f'[{audio_input}]{",".join(audio_filters)}[a]')
                audio_map = '[a]'
            else:
                audio_map = f'[{audio_input}]'

        args += ['-filter_complex', ';'.join(graph), '-map', '[v]']
        if media.has_audio:
            args += ['-map', audio_map, '-c:a', 'aac', '-b:a', '192k']
        else:
            args += ['-an']
    else:
        filters, complex_graph = video_filters(
            media, edits, asset, text_resources, trim.duration, trim=trim, cuts=cuts
        )
        if complex_graph:
            args += ['-filter_complex', filters, '-map', '[v]']
        else:
            args += ['-vf', filters, '-map', '0:v:0']
        if media.has_audio:
            audio_filters = audio_tempo_filters(edits.speed)
            out_duration = edits.output_duration(trim.duration)
            fade = fade_seconds(out_duration)
            if edits.fade.fade_in:
                audio_filters.append(f'afade=t=in:st=0:d={fade:.6f}')
            if edits.fade.fade_out:
                audio_filters.append(
                    f'afade=t=out:st={max(0, out_duration-fade):.6f}:d={fade:.6f}'
                )
            args += ['-map', '0:a:0']
            if audio_filters:
                args += ['-af', ','.join(audio_filters)]
            args += ['-c:a', 'aac', '-b:a', '192k']
        else:
            args += ['-an']

    args += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
             '-map_metadata', '-1', '-movflags', '+faststart', '-f', 'mp4', str(output)]
    return args
