"""Shared music trim, fades and source-driven dialogue ducking for both outputs."""
from .polish import fade_seconds


def input_loops(music):
    return music.loop and music.trim_start==0 and music.trim_end is None


def filters(music, duration, offset=0, total=None):
    total = total if total is not None else duration
    chain=[]
    trimmed=bool(music.trim_start or music.trim_end is not None)
    if trimmed:
        end=f':end={music.trim_end:.9f}' if music.trim_end is not None else ''
        chain += ['aresample=48000',f'atrim=start={music.trim_start:.9f}{end}','asetpts=PTS-STARTPTS']
        if music.loop:
            samples=round((music.trim_end-music.trim_start)*48000)
            chain += [f'aloop=loop=-1:size={max(1,samples)}','asetpts=N/SR/TB']
    chain += ['asetpts=PTS-STARTPTS',f'volume={music.music_volume:g}']
    if not music.loop:chain.append(f'apad=pad_dur={total:.6f}')
    chain.append(f'atrim=start=0:end={total:.6f}')
    fade=fade_seconds(total)
    if music.fade_in:chain.append(f'afade=t=in:st=0:d={fade:.6f}')
    if music.fade_out:chain.append(f'afade=t=out:st={max(0,total-fade):.6f}:d={fade:.6f}')
    if offset:chain += [f'atrim=start={offset:.9f}:end={offset+duration:.9f}','asetpts=PTS-STARTPTS']
    return chain


def duck(graph, source, music, output):
    """Audio-driven attenuation: source voice level controls only the music bed."""
    graph += [f'[{source}]asplit=2[{output}voice][{output}key]',
              f'[{music}][{output}key]sidechaincompress=threshold=0.035:ratio=8:attack=15:release=280:makeup=1[{output}]']
    return output+'voice', output
