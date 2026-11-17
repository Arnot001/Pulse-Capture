"""Generate six minutes of scattered original events and render a real mixed Short."""
from array import array
import argparse
import json
import math
from pathlib import Path
import threading
from unittest.mock import patch

from capture.ffmpeg_backend import discover
from editor.auto_ai import Pricing
from editor.auto_analysis import fingerprint, run_local
from editor.auto_job import AutoJob
from editor.auto_plan import AutoOptions, editor_state, overlap_seconds
from editor.auto_selection import source_ranges
from editor.auto_verify import verify_short
from editor.ffmpeg_export import build_export_command
from editor.media import probe_media
from editor.text_overlay import TextResources, TextOverlay, filter_path


def verify(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    backend=discover();cancel=threading.Event()
    source=output/'six-minute-scattered-events.mp4'
    starts=(15,55,95,135,175,215,255,295,335)
    active='+'.join(f'between(t,{at},{at+13})' for at in starts)
    if not source.exists():
        with TextResources(TextOverlay(True,'ORIGINAL SYNTHETIC EVENTS · SOURCE CLOCK')) as text:
            graph=(f"[0:v][1:v]overlay=enable='{active}':shortest=1,"
                   f"drawtext=fontfile={filter_path(text.font)}:text='%{{pts\\:hms}}':fontsize=22:fontcolor=white:"
                   f"box=1:boxcolor=black@0.7:x=10:y=10:enable='{active}'[v]")
            audio='0.3*sin(2*PI*(300*t+0.17*t*t))*('+active.replace(',',r'\,')+')'
            run_local([str(backend.ffmpeg),'-v','error','-nostdin','-n','-f','lavfi','-i','color=c=black:s=320x180:r=10:d=360',
                       '-f','lavfi','-i','testsrc2=s=320x180:r=10:d=360','-f','lavfi','-i',f'aevalsrc={audio}:s=48000:d=360',
                       '-filter_complex',graph,'-map','[v]','-map','2:a','-c:v','libx264','-preset','ultrafast','-crf','20',
                       '-c:a','aac','-t','360',str(source)],cancel,180)
    media=probe_media(backend.ffprobe,source);before=fingerprint(source,cancel)
    job=AutoJob(backend,media,AutoOptions(style='News/Preview',minimum=27,maximum=30),Pricing(),output/'cache')
    # Explicitly prove the missing optional speech model cannot block selection.
    with patch('editor.auto_transcribe.model_path',return_value=output/'missing-speech-model'),patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('Local mode made a network request')):
        job.prepare(cancel,lambda value:print(value,flush=True))
        payload,_=job.local(cancel)
    shorts=payload['plan']['shorts'];assert len(shorts)==3,shorts
    assert all(len(s['shots'])>=3 and s['shots'][-1]['start']-s['shots'][0]['start']>120 for s in shorts)
    overlaps=[overlap_seconds(a,b) for i,a in enumerate(shorts) for b in shorts[:i]]
    assert max(overlaps)<=8.5,overlaps
    # Cache reuse must not invoke any decoder or preserve the old continuous selector.
    again=AutoJob(backend,media,job.options,job.pricing,output/'cache')
    with patch('editor.auto_analysis.run_local',side_effect=AssertionError('Cached analysis decoded again')),patch('editor.auto_transcribe.model_path',return_value=output/'missing-speech-model'):
        again.prepare(cancel);cached,_=again.local(cancel)
    assert cached['plan']==payload['plan']
    short=shorts[0]
    transcript=[dict(start=a+1,end=a+12,text=f'Original synthetic scene {i+1}.') for i,a in enumerate(starts)]
    trim,cuts,edits=editor_state(short,media,transcript,style='News/Preview')
    destination=output/'separated-highlights-demo.mp4'
    with TextResources(edits.text) as text:
        run_local(build_export_command(backend.ffmpeg,media,trim,destination,edits,text_resources=text,cuts=cuts),cancel,180)
    expected=cuts.kept_duration(trim)
    verification=verify_short(backend,destination,expected,True,cancel)
    # Independently concatenate source PCM and compare it with the AAC export.
    pieces=[]
    for shot in short['shots']:
        raw=run_local([str(backend.ffmpeg),'-v','error','-i',str(source),'-af',
            f"atrim=start={shot['start']}:end={shot['end']},asetpts=PTS-STARTPTS",'-vn','-ac','1','-ar','8000','-f','f32le','-'],cancel)
        data=array('f');data.frombytes(raw);pieces.extend(data)
    raw=run_local([str(backend.ffmpeg),'-v','error','-i',str(destination),'-vn','-ac','1','-ar','8000','-f','f32le','-'],cancel)
    actual=array('f');actual.frombytes(raw)
    length=min(len(pieces),len(actual));a=pieces[:length];b=actual[:length]
    correlation=sum(x*y for x,y in zip(a,b))/math.sqrt(sum(x*x for x in a)*sum(y*y for y in b))
    assert correlation>.95,correlation
    assert abs(len(actual)/8000-expected)<.1
    assert fingerprint(source,cancel)==before
    report=dict(source=str(source),demo=str(destination),candidates=[dict(ranges=source_ranges(s['shots']),shots=s['shots'],
                duration=sum(x['end']-x['start'] for x in s['shots'])) for s in shorts],overlap_seconds=overlaps,
                audio_correlation=correlation,source_unchanged=True,cached_analysis_reused=True,paid_requests=0,
                missing_speech_model_supported=True,export=verification)
    (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    verify(parser.parse_args().output)
