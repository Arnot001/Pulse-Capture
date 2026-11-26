from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import pytest
from editor.media import probe_media
from editor.models import TrimRange
from editor.sequence import SourceClip,project_media
from editor.transforms import EditOptions,FULL_FRAME_FORMAT
from editor.cuts import CutPlan,CutRange
from editor.text_overlay import TextOverlay,Caption,TextResources
from editor.typography import CaptionStyle
from editor.preview import preview_command
from editor.playback_preview import playback_command
from editor.audio_preview import audio_preview_command
from editor.ffmpeg_export import build_export_command

pytestmark=pytest.mark.skipif(os.environ.get('PULSE_RUN_FFMPEG_TESTS')!='1',reason='Opt-in FFmpeg')


def run(command):
    result=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=60)
    assert result.returncode==0,result.stderr.decode('utf-8','replace')[-4000:]
    return result.stdout


@pytest.fixture
def sequence(tmp_path):
    ffmpeg=shutil.which('ffmpeg');probe=shutil.which('ffprobe')
    clips=[]
    for i,(colour,size,fps,tone) in enumerate((('red','320x180',24,440),('green','180x320',30,None),('blue','640x360',60,880))):
        path=tmp_path/f'clip {i}.mp4'
        args=[ffmpeg,'-v','error','-f','lavfi','-i',f'color={colour}:s={size}:r={fps}']
        if tone:args+=['-f','lavfi','-i',f'sine=frequency={tone}:sample_rate=44100']
        run(args+['-t','1.2','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)])
        clips.append(SourceClip.from_media(probe_media(probe,path)))
    clips=tuple(clips);media=project_media(clips)
    hashes={c.media.path:hashlib.sha256(c.media.path.read_bytes()).hexdigest() for c in clips}
    yield ffmpeg,probe,media,EditOptions(sequence=clips),tmp_path
    assert all(hashlib.sha256(path.read_bytes()).hexdigest()==digest for path,digest in hashes.items())


def rgb_frame(ffmpeg,path,time):
    return run([ffmpeg,'-v','error','-ss',str(time),'-i',str(path),'-frames:v','1','-vf','scale=32:18','-pix_fmt','rgb24','-f','rawvideo','pipe:1'])


def test_mixed_sequence_export_seek_audio_and_duration(sequence):
    ffmpeg,probe,media,edits,folder=sequence
    output=folder/'combined.mp4';trim=TrimRange(0,media.duration)
    run(build_export_command(ffmpeg,media,trim,output,edits))
    result=probe_media(probe,output)
    assert abs(result.duration-media.duration)<.08 and result.has_audio
    for at,channel in ((.5,0),(1.7,1),(2.9,2)):
        frame=rgb_frame(ffmpeg,output,at)
        centre=(9*32+16)*3
        pixel=frame[centre:centre+3]
        assert pixel[channel]>max(pixel[(channel+1)%3],pixel[(channel+2)%3])+35
        preview=run(preview_command(ffmpeg,media,at,160,90,edits,False,trim=trim,cuts=CutPlan()))
        assert preview.startswith(b'P6')
    pcm=run(audio_preview_command(ffmpeg,media,0,trim,edits=edits,seek_input=True))
    samples=struct.unpack('<'+'h'*(len(pcm)//2),pcm)
    def energy(start,end):
        segment=samples[int(start*96000):int(end*96000)]
        return sum(abs(x) for x in segment)/len(segment)
    assert energy(.3,.8)>100 and energy(1.5,1.9)<5 and energy(2.8,3.2)>100
    assert abs(len(pcm)/192000-media.duration)<.04
    with pytest.raises(ValueError,match='source clip'):
        build_export_command(ffmpeg,media,trim,edits.sequence[1].media.path,edits)


def test_vertical_caption_preview_playback_and_cut_export(sequence):
    ffmpeg,probe,media,edits,folder=sequence
    style=CaptionStyle(font_size=72,animation='none',italic=True,underline=True,
                       background_enabled=True,outline_colour='#FF00FF',shadow_colour='#00FFFF')
    edits=replace(edits.with_format(media,FULL_FRAME_FORMAT),text=TextOverlay(captions=(Caption(.1,3.4,'Caption test',style=style),)))
    trim=TrimRange(0,media.duration);cuts=CutPlan((CutRange(.8,1),))
    with TextResources(edits.text) as resources:
        output=folder/'vertical.mp4'
        run(build_export_command(ffmpeg,media,trim,output,edits,text_resources=resources,cuts=cuts))
        rendered=probe_media(probe,output)
        assert (rendered.width,rendered.height)==(1080,1920)
        assert abs(rendered.duration-cuts.kept_duration(trim))<.08
        still=run(preview_command(ffmpeg,media,1.7,180,320,edits,False,resources,trim,cuts))
        assert still.startswith(b'P6')
        frames=run(playback_command(ffmpeg,media,1.3,media.duration,trim,cuts,edits,90,160,resources))
        assert abs(len(frames)/(90*160*3*30)-(media.duration-1.3))<.08


def test_save_reload_and_legacy_single_source(sequence):
    from editor.project_file import save_project,load_project
    from editor.edit_history import EditSnapshot
    ffmpeg,probe,media,edits,folder=sequence
    edits=replace(edits,text=TextOverlay(captions=(Caption(1,2,'Persist',style=CaptionStyle(underline=True)),)))
    state=EditSnapshot(TrimRange(0,media.duration),CutPlan(),edits)
    path=folder/'edit.pulse.json';save_project(path,media,state)
    assert load_project(path)==(media,state)
    single=edits.sequence[0].media
    state=EditSnapshot(TrimRange(0,single.duration),CutPlan(),EditOptions())
    save_project(path,single,state)
    data=json.loads(path.read_text());data['version']=1
    del data['state']['values']['edits']['values']['sequence']
    del data['state']['values']['edits']['values']['overlay_anchor']
    path.write_text(json.dumps(data))
    assert load_project(path)==(single,state)
    data['media']['values']['path']={'path':str(folder/'missing.mp4')}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='Missing source'):load_project(path)
