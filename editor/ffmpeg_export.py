"""Pure non-destructive edit/export command construction."""
from pathlib import Path

from branding import watermark_path
from .cuts import CutPlan
from .music import resolve_music_path
from .music_mix import input_loops, filters as music_filters, duck
from .crop_motion import motion_crop_filter
from .transforms import EditOptions, video_filters
from .polish import fade_seconds, audio_tempo_filters


def _cut_filter_graph(media, trim, cuts, source_crop=None):
    """Build source-time trim/concat filters and return graph plus output labels."""
    segments = cuts.kept_segments(trim)
    if not segments:
        raise ValueError('Cuts would remove the entire selected video. Restore a section first.')

    graph = []
    video_labels, audio_labels = [], []
    for index, segment in enumerate(segments):
        video = f'cutv{index}'
        # Motion must run BEFORE source-time cuts. After concat, FFmpeg's t
        # reflects shortened output time and would no longer match keyframes.
        crop_before_trim = f'{source_crop},' if source_crop else ''
        graph.append(
            f'[0:v:0]{crop_before_trim}trim=start={segment.start:.9f}:end={segment.end:.9f},'
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
    return music_filters(edits.music, out_duration)


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
        if input_loops(edits.music):
            args += ['-stream_loop', '-1']
        args += ['-i', str(music_path)]

    graph = []
    if active_cuts:
        source_crop = (motion_crop_filter(edits.crop, edits.crop_motion)
                       if edits.crop_motion.keyframes else None)
        cut_graph, video_input, audio_input = _cut_filter_graph(
            media, trim, cuts, source_crop)
        graph.extend(cut_graph)
    else:
        video_input = '0:v:0'
        audio_input = '0:a:0' if media.has_audio else None

    filters, visual_complex = video_filters(
        media, edits, asset, text_resources, kept_duration,
        input_label=video_input, trim=trim, cuts=cuts,
        skip_crop=active_cuts and bool(edits.crop_motion.keyframes)
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
            source_label, music_label = ('sourcea','musica')
            if edits.music.duck_dialogue:
                source_label, music_label = duck(graph,source_label,music_label,'duckedmusic')
            graph.append(
                f'[{source_label}][{music_label}]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,'
                f'alimiter=limit=0.95:level=false:latency=true,atrim=start=0:end={out_duration:.6f}[a]'
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
    from .reactions import augment_export, validate_cues
    validate_cues(edits.sounds, edits.overlays, out_duration)
    from .imported_media import validate_clips
    validate_clips(edits.media_clips, out_duration)
    width, height = edits.encoded_size(media)
    return augment_export(args, edits, out_duration, width, height, edits.bands(media))


def build_plan_segment_command(ffmpeg, media, item, output, framing, text_resources=None):
    """Compile a validated timeline element through the existing visual pipeline.

    Intermediate elements have identical dimensions, CFR and audio layout so
    source audio can be concatenated/replayed without clock discontinuities.
    Paths are application-owned, never values taken from plan JSON.
    """
    from dataclasses import replace
    from .models import TrimRange
    from .polish import Zoom
    from .pulse_plan import element_duration
    from .text_overlay import TextOverlay, _drawtext
    from .transforms import FULL_FRAME_FORMAT, SHORTS_FORMAT

    duration = element_duration(item)
    silent = item['kind'] != 'shot' or not media.has_audio
    if item['kind'] == 'title':
        text = TextOverlay(True, item['text'], position='Centre', safe_area=True)
        draw = _drawtext(1080, 1920, text, text_resources, text_resources.path)
        # The requested title font size is validated against the safe canvas.
        import re
        size = item.get('font_size', 64)
        draw = re.sub(r'fontsize=\d+', f'fontsize={size}', draw)
        animation = item.get('animation', 'fade')
        ramp = min(.2, duration/3)
        if animation == 'fade':
            draw += f":alpha='min(1,min(t/{ramp:.9f},({duration:.9f}-t)/{ramp:.9f}))'"
        elif animation == 'slide':
            draw = draw.replace('x=(w-text_w)/2', f"x='(w-text_w)/2-w*max(0,1-t/{ramp:.9f})'")
        elif animation == 'pop':
            draw = draw.replace(f'fontsize={size}', f"fontsize='{size}*(0.7+0.3*min(1,t/{ramp:.9f}))'")
        elif animation == 'typewriter':
            from .text_overlay import filter_path
            parts = []
            reveal = min(.6, duration*.6)
            for index in range(1, len(item['text'])+1):
                path = text_resources.path.parent / f'reveal-{index}.txt'
                path.write_text(item['text'][:index], encoding='utf-8')
                partial = draw.replace(filter_path(text_resources.path), filter_path(path))
                start = (index-1)*reveal/len(item['text'])
                end = index*reveal/len(item['text']) if index < len(item['text']) else duration
                parts.append(partial + f":enable='gte(t,{start:.9f})*lt(t,{end:.9f})'")
            draw = ','.join(parts)
        args = [str(ffmpeg), '-hide_banner', '-v', 'error', '-nostdin', '-n',
                '-f', 'lavfi', '-i', 'color=c=0x101820:s=1080x1920:r=30',
                '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                '-vf', draw, '-map', '0:v:0', '-map', '1:a:0',
                '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k', '-t', f'{duration:.9f}', '-movflags', '+faststart', str(output)]
        return args

    preset = FULL_FRAME_FORMAT if framing in ('full_frame','comedy_bands') else SHORTS_FORMAT
    edits = EditOptions().with_format(media, preset)
    if 'zoom' in item:
        zoom = item['zoom']
        edits = replace(edits, zoom=Zoom(True, zoom['factor'], zoom['x'], zoom['y']))
    if item['kind'] == 'shot':
        trim = TrimRange(item['start'], item['end'])
        edits = replace(edits, speed=item.get('speed', 1))
    else:
        trim = TrimRange(item['source_time'], item['source_time']+1/media.fps)
    args = build_export_command(ffmpeg, media, trim, output, edits)
    # Freeze just the selected first decoded frame; deliberately silent audio.
    if item['kind'] == 'freeze':
        tail = f'trim=end_frame=1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={duration:.9f},fps=30'
        if '-vf' in args:
            at = args.index('-vf')+1
            args[at] += ',' + tail
        else:
            at = args.index('-filter_complex')+1
            args[at] = args[at].replace('[v]', '[freezeinput]') + f';[freezeinput]{tail}[v]'
    effect = item.get('effect')
    if effect:
        effects = {
            'punch_zoom': "zoompan=z='1+0.5*min(1,on/5)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s=1080x1920:fps=30",
            'shake': "scale=1112:1978,crop=1080:1920:x='16+12*sin(t*70)*lt(t,.35)':y='29+12*cos(t*60)*lt(t,.35)'",
            'scratch': "hue=s=0:enable='lt(t,.2)',drawbox=x=0:y=ih*.48:w=iw:h=8:c=white@.5:t=fill:enable='lt(t,.2)'",
            'glitch': "rgbashift=rh=12:bh=-12:enable='lt(t,.3)'",
        }
        tail = effects[effect]
        if framing == 'comedy_bands':
            from .transforms import full_frame_geometry
            x,y,w,h = full_frame_geometry(media)
            # Keep interruptions inside the picture; never enlarge gameplay into a band.
            tail = tail.replace('1080x1920',f'{w}x{h}')
            if effect=='shake':
                tail = f"scale={w+32}:{h+58},crop={w}:{h}:x='16+12*sin(t*70)*lt(t,.35)':y='29+12*cos(t*60)*lt(t,.35)'"
            tail = f'crop={w}:{h}:{x}:{y},'+tail+f',pad=1080:1920:{x}:{y}:color=0x101820'
        if '-vf' in args:
            args[args.index('-vf')+1] += ',' + tail
        else:
            at = args.index('-filter_complex')+1
            args[at] = args[at].replace('[v]', '[effectinput]') + f';[effectinput]{tail}[v]'
    if silent:
        # Remove the original audio mapping/options before binding generated silence.
        if '-an' in args:
            args.remove('-an')
        if '0:a:0' in args:
            at = args.index('0:a:0')-1
            del args[at:at+2]
        for flag in ('-af', '-c:a', '-b:a'):
            if flag in args:
                at = args.index(flag)
                del args[at:at+2]
        at = args.index('-i')+2
        args[at:at] = ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
        args[-1:-1] = ['-map', '1:a:0', '-c:a', 'aac', '-b:a', '192k']
    audio_tail = f'volume={item.get("volume", 1):g},apad,atrim=duration={duration:.9f}'
    if '-af' in args:
        args[args.index('-af')+1] += ',' + audio_tail
    else:
        args[-1:-1] = ['-af', audio_tail]
    args[-1:-1] = ['-r', '30', '-fps_mode', 'cfr', '-ar', '48000', '-ac', '2', '-t', f'{duration:.9f}']
    return args


def build_plan_join_command(ffmpeg, left, right, output, elapsed, transition, duration):
    """Join normalized elements with a named, bounded transition and matching audio."""
    seconds = transition.get('duration', 0)
    graph = ['[0:v]settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[v0]',
             '[1:v]settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[v1]',
             '[0:a]asetpts=PTS-STARTPTS[a0]', '[1:a]asetpts=PTS-STARTPTS[a1]']
    if transition.get('type', 'cut') == 'cut':
        graph.append('[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]')
    else:
        # A YUV black frame has luma 16 and chroma 128, not zero planes.
        black = 'if(eq(PLANE,0),16,128)'
        name = ('fade' if transition['type'] == 'dissolve' else
                f"custom:expr='if(lte(P,0.5),(B-({black}))*(1-2*P)+({black}),"
                f"(A-({black}))*(2*P-1)+({black}))'")
        graph += [f'[v0][v1]xfade=transition={name}:duration={seconds:.9f}:offset={elapsed-seconds:.9f}[v]',
                  f'[a0][a1]acrossfade=d={seconds:.9f}:c1=tri:c2=tri[a]']
    return [str(ffmpeg), '-hide_banner', '-v', 'error', '-nostdin', '-n',
            '-i', str(left), '-i', str(right), '-filter_complex_threads', '1',
            '-filter_complex', ';'.join(graph), '-map', '[v]', '-map', '[a]',
            '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-pix_fmt', 'yuv420p',
            '-r', '30', '-fps_mode', 'cfr', '-c:a', 'aac', '-b:a', '192k',
            '-ar', '48000', '-ac', '2', '-t', f'{duration:.9f}', '-movflags', '+faststart', str(output)]
