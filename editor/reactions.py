"""Validated output-clock cues and shared FFmpeg compilers for preview/export."""
from dataclasses import dataclass
import math
from .reaction_library import ReactionLibrary


def finite(value, low, high, label):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{label}: use a finite number from {low} to {high}.')


@dataclass(frozen=True)
class SoundCue:
    asset_id: str
    at: float
    volume: float = .75
    duck_source: float = 1
    duration: float | None = None
    fade_in: float = .005
    fade_out: float = .03

    def length(self, library=None):
        if self.asset_id == 'silence.pause':
            return self.duration if self.duration is not None else 1.8
        length = (library or ReactionLibrary()).metadata(self.asset_id, 'sfx')['duration']
        return length if self.duration is None else min(length, self.duration)

    def validate(self, total=None):
        finite(self.at, 0, 86400, 'Sound time')
        finite(self.volume, 0, 2, 'Sound volume')
        finite(self.duck_source, 0, 1, 'Background gain')
        finite(self.fade_in, 0, 1, 'Fade in')
        finite(self.fade_out, 0, 1, 'Fade out')
        if self.duration is not None:
            finite(self.duration, .01, 20, 'Sound duration')
        self.length()
        if self.asset_id.startswith('import.'):
            ReactionLibrary().resolve(self.asset_id,'sfx')
        if total is not None and self.at >= total:
            raise ValueError('Sound starts outside the output timeline.')


POSITIONS = ('top_left', 'top_right', 'bottom_left', 'bottom_right', 'centre')
ANIMATIONS = ('none', 'fade', 'pop', 'bounce', 'shake', 'spin')


@dataclass(frozen=True)
class VisualCue:
    kind: str
    asset_id: str
    start: float
    end: float
    position: str = 'bottom_right'
    scale: float = .2
    loop: bool = True
    opacity: float = 1
    rotation: float = 0
    animation: str = 'none'
    x: float | None = None
    y: float | None = None
    zone: str = 'canvas'

    def validate(self, total=None):
        if self.kind not in ('emoji', 'gif'):
            raise ValueError('Overlay kind must be emoji or gif.')
        ReactionLibrary().metadata(self.asset_id, self.kind)
        ReactionLibrary().resolve(self.asset_id, self.kind)
        if self.zone not in ('canvas','top','bottom'):
            raise ValueError('Overlay zone must be canvas, top or bottom.')
        finite(self.start, 0, 86400, 'Overlay start')
        finite(self.end, .01, 86400, 'Overlay end')
        if self.end <= self.start or (total is not None and self.end > total+.00001):
            raise ValueError('Overlay must have a positive interval inside the output.')
        if self.position not in POSITIONS or self.animation not in ANIMATIONS or type(self.loop) is not bool:
            raise ValueError('Unsupported overlay position, animation or loop setting.')
        finite(self.scale, .05, .6, 'Overlay scale')
        finite(self.opacity, 0, 1, 'Overlay opacity')
        finite(self.rotation, -180, 180, 'Overlay rotation')
        if (self.x is None) != (self.y is None):
            raise ValueError('Supply both normalized x and y or neither.')
        for value in (self.x, self.y):
            if value is not None:
                finite(value, 0, 1, 'Overlay position')


def validate_cues(sounds, overlays, total=None):
    if len(sounds) > 64 or len(overlays) > 24:
        raise ValueError('Use at most 64 sounds and 24 visual overlays.')
    for cue in (*sounds, *overlays):
        cue.validate(total)
    for time in (c.start for c in overlays):
        if sum(c.start <= time < c.end for c in overlays) > 6:
            raise ValueError('Use at most six simultaneous visual overlays.')


def add_sounds(args, graph, input_label, sounds, duration, offset=0):
    """Mix the existing source/music bus; offset makes seeking sample-accurate."""
    library = ReactionLibrary()
    cues = [c for c in sounds if c.at < duration+offset and c.at+c.length(library) > offset]
    labels, gains = [], []
    next_input = args.count('-i')
    for i, cue in enumerate(cues):
        length = min(cue.length(library), duration+offset-cue.at)
        start, end = max(0, cue.at-offset), cue.at+length-offset
        gain = 0 if cue.asset_id == 'silence.pause' else cue.duck_source
        # 30 ms gain ramps avoid clicks; overlapping ducks choose the strongest.
        gains.append(f'if(between(t,{start:.9f},{end:.9f}),{gain:g},'
                     f'if(between(t,{start-.03:.9f},{start:.9f}),1-(1-{gain:g})*(t-({start-.03:.9f}))/.03,'
                     f'if(between(t,{end:.9f},{end+.03:.9f}),{gain:g}+(1-{gain:g})*(t-{end:.9f})/.03,1)))')
        if cue.asset_id == 'silence.pause':
            continue
        args += ['-i', str(library.resolve(cue.asset_id, 'sfx'))]
        label = f'sfx{i}'
        skipped = max(0, offset-cue.at)
        graph.append(f'[{next_input}:a]aresample=48000,asetpts=PTS-STARTPTS,atrim=duration={length:.9f},'
                     f'volume={cue.volume:g},afade=t=in:d={min(cue.fade_in,length/2):.9f},'
                     f'afade=t=out:st={max(0,length-cue.fade_out):.9f}:d={min(cue.fade_out,length):.9f},'
                     f'atrim=start={skipped:.9f},asetpts=PTS-STARTPTS,'
                     f'adelay={round(start*48000)}S:all=1[{label}]')
        next_input += 1
        labels.append(label)
    gain = '1'
    for expression in gains:
        gain = f'min({gain},{expression})'
    if input_label:
        graph.append(f'[{input_label}]aresample=48000,volume=\'{gain}\':eval=frame,'
                     f'apad,atrim=duration={duration:.9f}[sfxbed]')
    else:
        graph.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={duration:.9f}[sfxbed]')
    graph.append('[sfxbed]'+''.join(f'[{label}]' for label in labels)+
                 f'amix=inputs={len(labels)+1}:normalize=0:duration=first:dropout_transition=0,'
                 f'alimiter=limit=0.90:level=false:latency=true,atrim=duration={duration:.9f}[reactionaudio]')
    return 'reactionaudio'


def add_visuals(args, graph, input_label, overlays, width, height, sample_time=None, bands=None):
    """One compositor for still previews and MP4. Rotated bounds stay inside safe areas."""
    current = input_label
    library = ReactionLibrary()
    for i, cue in enumerate(overlays):
        if sample_time is not None and not cue.start <= sample_time < cue.end:
            continue
        item = library.metadata(cue.asset_id, cue.kind)
        if cue.kind == 'gif' and not cue.loop:
            end = min(cue.end, cue.start+item['duration'])
            if sample_time is not None and sample_time >= end:
                continue
        else:
            end = cue.end
        index = args.count('-i')
        if cue.kind == 'emoji':
            args += ['-loop', '1']
        else:
            args += ['-ignore_loop', '1']
            if cue.loop:
                args += ['-stream_loop', '-1']
        elapsed = (sample_time-cue.start) if sample_time is not None else 0
        if sample_time is not None and cue.kind == 'gif':
            args += ['-ss', f'{elapsed % item["duration"] if cue.loop else elapsed:.9f}']
        args += ['-i', str(library.resolve(cue.asset_id, cue.kind))]
        from .comedy_layout import overlay_region, overlay_size
        region = overlay_region(cue,bands,width,height)
        size = overlay_size(cue,width,height,region)
        clock = str(elapsed) if sample_time is not None else 't'
        duration = end-cue.start
        ramp = min(.15, duration/3)
        factor = f'(0.65+0.35*min(1,({clock})/{ramp}))' if cue.animation == 'pop' else '1'
        filters = [f'scale=w=\'{size}*{factor}\':h=\'{size}*{factor}\':force_original_aspect_ratio=decrease:eval=frame', 'format=rgba',
                   f'colorchannelmixer=aa={cue.opacity:g}']
        angle = f'{cue.rotation:g}*PI/180'
        if cue.animation == 'spin':
            angle += f'+2*PI*min(1,({clock})/.5)'
        filters.append(f"rotate='{angle}':ow='hypot(iw,ih)':oh=ow:c=none")
        if cue.animation != 'none':
            if sample_time is None:
                filters += [f'fade=t=in:d={ramp}:alpha=1', f'fade=t=out:st={duration-ramp}:d={ramp}:alpha=1']
            else:
                alpha = max(0, min(1, elapsed/ramp, (duration-elapsed)/ramp))
                filters.append(f'colorchannelmixer=aa={alpha:g}')
        filters.append(f'setpts=PTS-STARTPTS+{cue.start if sample_time is None else 0:.9f}/TB')
        mark = f'reaction{i}'
        graph.append(f'[{index}:v]'+','.join(filters)+f'[{mark}]')
        x = f'{cue.x:g}*(W-w)' if cue.x is not None else 'W-w-W*.1' if 'right' in cue.position else 'W*.1' if 'left' in cue.position else '(W-w)/2'
        y = f'{cue.y:g}*(H-h)' if cue.y is not None else 'H*.12' if 'top' in cue.position else 'H*.78-h' if 'bottom' in cue.position else '(H-h)/2'
        motion_time = str(elapsed) if sample_time is not None else f'(t-{cue.start:.9f})'
        if cue.animation == 'bounce':
            y += f'-{size*.12:g}*abs(sin({motion_time}*14))*exp(-{motion_time}*4)'
        if cue.animation == 'shake':
            x += f'+{size*.04:g}*sin({motion_time}*70)'
        if cue.zone!='canvas':
            x = f'{region.x}+{cue.x if cue.x is not None else 1 if "right" in cue.position else 0 if "left" in cue.position else .5}*({region.width}-w)'
            y = f'{region.y}+{cue.y if cue.y is not None else .5}*({region.height}-h)'
            if cue.animation=='bounce':y+=f'-{size*.12:g}*abs(sin({motion_time}*14))*exp(-{motion_time}*4)'
            if cue.animation=='shake':x+=f'+{size*.04:g}*sin({motion_time}*70)'
        x = f'max({region.x},min({region.x+region.width}-w,{x}))'
        y = f'max({region.y},min({region.y+region.height}-h,{y}))'
        enable = '' if sample_time is not None else f":enable='gte(t,{cue.start:.9f})*lt(t,{end:.9f})'"
        output = f'reactionv{i}'
        graph.append(f"[{current}][{mark}]overlay=x='{x}':y='{y}':eof_action=pass:repeatlast=0:format=auto{enable}[{output}]")
        current = output
    return current


def augment_export(args, edits, duration, width, height, bands=None):
    """Extend an existing export command, preserving its video/audio transforms."""
    if not edits.sounds and not edits.overlays and not edits.narration and not edits.media_clips:
        return args
    args = list(args)
    output = args.pop()
    graph = []
    if '-filter_complex' in args:
        at = args.index('-filter_complex')
        graph.append(args[at+1])
        del args[at:at+2]
    map_indices = [i for i,v in enumerate(args) if v == '-map']
    video = args[map_indices[0]+1]
    if '-vf' in args:
        at = args.index('-vf')
        graph.append(f'[{video}]{args[at+1]}[reactionbasev]')
        del args[at:at+2]
        video = '[reactionbasev]'
    maps = []
    while '-map' in args:
        at = args.index('-map')
        maps.append(args[at+1])
        del args[at:at+2]
    audio = maps[1].strip('[]') if len(maps)>1 else None
    if '-af' in args:
        at = args.index('-af')
        graph.append(f'[{audio}]{args[at+1]}[reactionbasea]')
        del args[at:at+2]
        audio = 'reactionbasea'
    # New inputs must precede output codec/options in FFmpeg's option groups.
    # add_* uses the existing input count to assign stream indexes.
    inputs = ['-i']*args.count('-i')
    initial = len(inputs)
    if edits.media_clips:
        from .imported_media import add_media
        video = add_media(inputs, graph, video.strip('[]'), edits.media_clips, width, height)
    video = add_visuals(inputs, graph, video.strip('[]'), edits.overlays, width, height, bands=bands)
    if edits.sounds:
        audio = add_sounds(inputs, graph, audio, edits.sounds, duration)
    if edits.narration:
        from .narration import add_narration
        audio = add_narration(inputs, graph, audio, edits.narration, duration)
    if edits.sounds or edits.narration:
        if '-an' in args:
            args.remove('-an')
        if '-c:a' not in args:
            args += ['-c:a', 'aac', '-b:a', '192k']
    # Place extra inputs immediately after the last original input filename.
    at = max(i for i,v in enumerate(args) if v == '-i')+2
    args[at:at] = inputs[initial:]
    args += ['-filter_complex_threads', '1', '-filter_complex', ';'.join(graph), '-map', f'[{video}]' if video != '0:v:0' else video]
    if audio:
        args += ['-map', f'[{audio}]' if ':' not in audio else audio]
    args += ['-t', f'{duration:.9f}', output]
    return args
