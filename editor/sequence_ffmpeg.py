"""Replace the primary input with an unencoded, normalized clip sequence.

The existing visual/audio compilers retain their clocks and effects. Still seeks
open only the active source; continuous output uses bounded FFmpeg queues and
one filter thread. No source or intermediate media is written.
"""
import re
from pathlib import Path
from .sequence import positions, validate_sequence


def sequence_command(command, media, edits, *, still=False):
    clips=getattr(edits,'sequence',())
    if not clips:return command
    validate_sequence(clips,True)
    args=list(command)
    first=args.index('-i')
    prefix=args[:first]
    start=0.0;duration=media.duration
    for flag in ('-ss','-t'):
        if flag in prefix:
            at=prefix.index(flag)
            value=float(prefix[at+1])
            if flag=='-ss':start=value
            else:duration=value
            del prefix[at:at+2]
    end=min(media.duration,start+duration)
    if still:end=min(end,start+max(.1,2/media.fps))
    parts=[]
    for clip,a,b in positions(clips):
        lo,hi=max(a,start),min(b,end)
        if hi>lo+1e-9:parts.append((clip,clip.start+lo-a,hi-lo))
    if not parts:raise ValueError('No source frames at this project position.')
    tail=args[first+2:]
    graph=''
    if '-filter_complex' in tail:
        at=tail.index('-filter_complex');graph=tail[at+1];del tail[at:at+2]
    # Simple primary-stream filters must become branches of the same graph.
    for kind,flag,noop in (('v','-vf','null'),('a','-af','anull')):
        simple=None
        if flag in tail:
            at=tail.index(flag);simple=tail[at+1];del tail[at:at+2]
        for at in range(len(tail)-1):
            if tail[at]=='-map' and tail[at+1] in (f'0:{kind}',f'0:{kind}:0',f'0:{kind}:0?'):
                label=f'seqmapped{kind}'
                graph+=(';' if graph else '')+f'[0:{kind}:0]{simple or noop}[{label}]'
                tail[at+1]=f'[{label}]'
    used={kind:len(re.findall(r'\[0:'+kind+r'(?::0)?\]',graph)) for kind in ('v','a')}
    # Later inputs (music, logo, GIFs, commentary) retain their original meaning.
    def shift(match):
        index=int(match[1]);kind=match[2];suffix=match[3] or ''
        return f'[{index+len(parts)-1}:{kind}{suffix}]' if index else match[0]
    graph=re.sub(r'\[(\d+):([av])(:\d+)?\]',shift,graph)
    for at in range(len(tail)-1):
        if tail[at]=='-map' and re.fullmatch(r'\d+:[av](?::\d+)?\??',tail[at+1]):
            index,rest=tail[at+1].split(':',1)
            tail[at+1]=f'{int(index)+len(parts)-1}:{rest}'
    inputs=[];normal=[]
    width,height=(media.width+1)//2*2,(media.height+1)//2*2
    for index,(clip,source,length) in enumerate(parts):
        inputs+=['-threads','1','-ss',f'{source:.9f}','-t',f'{length:.9f}','-i',str(clip.media.path)]
        if used['v']:
            normal.append(f'[{index}:v:0]setpts=PTS-STARTPTS,fps=30,'
                f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,'
                f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x101820,setsar=1,'
                f'tpad=stop_mode=clone:stop_duration={length:.9f},trim=duration={length:.9f},'
                f'settb=AVTB,setpts=PTS-STARTPTS[seqv{index}]')
        if used['a']:
            audio=(f'[{index}:a:0]asetpts=PTS-STARTPTS,aresample=48000:async=1:first_pts=0,'
                   'aformat=sample_fmts=fltp:channel_layouts=stereo,apad' if clip.media.has_audio else
                   'anullsrc=r=48000:cl=stereo')
            normal.append(audio+f',atrim=duration={length:.9f},asetpts=PTS-STARTPTS[seqa{index}]')
    kinds=[kind for kind in ('v','a') if used[kind]]
    if not kinds:raise ValueError('Sequence command has no mapped source streams.')
    joined=''.join(f'[seq{kind}{index}]' for index in range(len(parts)) for kind in kinds)
    normal.append(joined+f'concat=n={len(parts)}:v={int(bool(used["v"]))}:a={int(bool(used["a"]))}'+''.join(f'[seq{kind}]' for kind in kinds))
    for kind in kinds:
        count=used[kind]
        if count>1:
            split='split' if kind=='v' else 'asplit'
            normal.append(f'[seq{kind}]{split}={count}'+''.join(f'[seq{kind}use{i}]' for i in range(count)))
        counter=iter(range(count))
        graph=re.sub(r'\[0:'+kind+r'(?::0)?\]',lambda _, k=kind,n=count,c=counter:f'[seq{k}use{next(c)}]' if n>1 else f'[seq{k}]',graph)
    # Always one filter worker; queues stay bounded by FFmpeg and preview readers.
    if '-filter_complex_threads' in tail:
        at=tail.index('-filter_complex_threads');del tail[at:at+2]
    return prefix+inputs+tail[:-1]+['-filter_complex_threads','1','-filter_complex',';'.join(normal+[graph])]+tail[-1:]


def protect_sources(output, edits):
    target=Path(output).resolve()
    if any(target==clip.media.path.resolve() for clip in getattr(edits,'sequence',())):
        raise ValueError('An export must never overwrite any source clip.')
