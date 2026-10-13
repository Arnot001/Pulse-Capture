"""Pure non-destructive edit/export command construction."""
from pathlib import Path

from branding import watermark_path
from .cuts import CutPlan
from .music import resolve_music_path
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


def _source_audio_filters(edits, out_duration):
    filters = audio_tempo_filters(edits.speed)
    if edits.music.enabled and edits.music.original_volume != 1:
        filters.append(f'volume={edits.music.original_volume:g}')
    fade = fade_seconds(out_duration)
    if edits.fade.fade_in:
        filters.append(f'afade=t=in:st=0:d={fade:.6f}')
    if edits.fade.fade_out:
        filters.append(f'afade=t=out:st={max(0, out_duration-fade):.6f}:d={fade:.6f}')
    return filters


def _music_audio_filters(edits, out_duration):
    music = edits.music
    filters = ['asetpts=PTS-STARTPTS', f'volume={music.music_volume:g}']
    if not music.loop:
        filters.append(f'apad=pad_dur={out_duration:.6f}')
    filters.append(f'atrim=start=0:end={out_duration:.6f}')
    fade = fade_seconds(out_duration)
    if music.fade_in:
        filters.append(f'afade=t=in:st=0:d={fade:.6f}')
    if music.fade_out:
        filters.append(f'afade=t=out:st={max(0, out_duration-fade):.6f}:d={fade:.6f}')
    return filters


def build_export_command(ffmpeg, media, trim, output, edits=None, asset=None,
                         text_resources=None, cuts=None, music_path=None):
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
    out_duration = edits.output_duration(kept_duration)
    if edits.music.enabled:
        music_path = Path(music_path) if music_path is not None else resolve_music_path(edits.music)
        if not music_path.is_file():
            raise ValueError('Music file could not be found. Choose another track.')

    args = [str(ffmpeg), '-hide_banner', '-loglevel', 'warning', '-nostdin', '-n',
            '-stats_period', '0.25', '-progress', 'pipe:1']
    if active_cuts:
        args += ['-i', str(media.path)]
    else:
        args += ['-ss', f'{trim.start:.6f}', '-t', f'{trim.duration:.6f}', '-i', str(media.path)]

    if edits.branding.enabled:
        args += ['-i', str(asset)]

    music_index = None
    if edits.music.enabled:
        music_index = 2 if edits.branding.enabled else 1
        if edits.music.loop:
            args += ['-stream_loop', '-1']
        args += ['-i', str(music_path)]

    graph = []
    if active_cuts:
        cut_graph, video_input, audio_input = _cut_filter_graph(media, trim, cuts)
        graph.extend(cut_graph)
    else:
        video_input = '0:v:0'
        audio_input = '0:a:0' if media.has_audio else None

    filters, visual_complex = video_filters(
        media, edits, asset, text_resources, kept_duration,
        input_label=video_input, trim=trim, cuts=cuts
    )

    if active_cuts:
        if visual_complex:
            graph.append(filters)
        else:
            graph.append(f'[{video_input}]{filters}[v]')
        video_map = '[v]'
        simple_video = None
    elif visual_complex:
        graph.append(filters)
        video_map = '[v]'
        simple_video = None
    else:
        video_map = '0:v:0'
        simple_video = filters

    audio_map = None
    if edits.music.enabled:
        if media.has_audio:
            source_filters = _source_audio_filters(edits, out_duration)
            if source_filters:
                graph.append(f'[{audio_input}]{",".join(source_filters)}[sourcea]')
            else:
                graph.append(f'[{audio_input}]anull[sourcea]')
        graph.append(
            f'[{music_index}:a:0]{",".join(_music_audio_filters(edits, out_duration))}[musica]'
        )
        if media.has_audio:
            graph.append(
                f'[sourcea][musica]amix=inputs=2:duration=longest:dropout_transition=0,'
                f'atrim=start=0:end={out_duration:.6f}[a]'
            )
        else:
            graph.append(f'[musica]anull[a]')
        audio_map = '[a]'
    elif media.has_audio and active_cuts:
        source_filters = _source_audio_filters(edits, out_duration)
        if source_filters:
            graph.append(f'[{audio_input}]{",".join(source_filters)}[a]')
            audio_map = '[a]'
        else:
            audio_map = f'[{audio_input}]'

    if graph:
        args += ['-filter_complex', ';'.join(graph)]

    if simple_video is not None:
        args += ['-vf', simple_video]
    args += ['-map', video_map]

    if edits.music.enabled:
        args += ['-map', audio_map, '-c:a', 'aac', '-b:a', '192k']
    elif media.has_audio:
        if active_cuts:
            args += ['-map', audio_map, '-c:a', 'aac', '-b:a', '192k']
        else:
            source_filters = _source_audio_filters(edits, out_duration)
            args += ['-map', '0:a:0']
            if source_filters:
                args += ['-af', ','.join(source_filters)]
            args += ['-c:a', 'aac', '-b:a', '192k']
    else:
        args += ['-an']

    args += ['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
             '-map_metadata', '-1', '-movflags', '+faststart', '-f', 'mp4', str(output)]
    return args
