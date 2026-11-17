"""Real MP4/PCM/image acceptance checks. PULSE_RUN_FFMPEG_TESTS=1."""
from array import array
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import Backend, run, validate_output, validate_audio_coverage
from editor.media import probe_media
from editor.models import TrimRange
from editor.pulse_plan import starter_plan, source_identity, pulse_editor_state, validate_pulse_plan
from editor.pulse_job import assemble_plan
from editor.reaction_library import ReactionLibrary, ASSETS
from editor.reactions import SoundCue, VisualCue
from editor.ffmpeg_export import build_export_command, build_plan_segment_command
from editor.audio_preview import audio_preview_command
from editor.text_overlay import TextResources, TextOverlay
from editor.preview import preview_command
from editor.transforms import EditOptions


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS')=='1','Opt-in real FFmpeg integration')
class ComedyRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.env=patch.dict(os.environ,PULSE_REACTION_LIBRARY=str(cls.root/'library'));cls.env.start()
        cls.backend=Backend(shutil.which('ffmpeg'),shutil.which('ffprobe'),True)
        cls.source=cls.root/'fixture.mp4'
        made=run([cls.backend.ffmpeg,'-v','error','-nostdin','-n','-f','lavfi','-i',
                  'color=c=0x204060:s=640x360:r=30','-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                  '-t','4','-c:v','libx264','-c:a','aac',str(cls.source)],30)
        if made.returncode:raise RuntimeError(made.stderr)
        cls.media=probe_media(cls.backend.ffprobe,cls.source)
        cls.gif=cls.root/'original.gif'
        made=run([cls.backend.ffmpeg,'-v','error','-nostdin','-n','-loop','1','-i',str(ASSETS/'emoji'/'emoji.siren.png'),
                  '-filter_complex',"trim=duration=1,fps=10,rotate='.4*sin(t*12)':c=none,split[a][b];[a]palettegen=reserve_transparent=1[p];[b][p]paletteuse=alpha_threshold=128",
                  '-t','1','-loop','0',str(cls.gif)],30)
        if made.returncode:raise RuntimeError(made.stderr)
        cls.gif_id=ReactionLibrary().import_file(cls.gif,'gif',cls.backend.ffmpeg,cls.backend.ffprobe)

    @classmethod
    def tearDownClass(cls):
        cls.env.stop();cls.temp.cleanup()

    def render(self,edits,name,media=None,trim=None):
        media=media or self.media;trim=trim or TrimRange(0,media.duration)
        out=self.root/name
        with TextResources(edits.text) as resources:
            result=run(build_export_command(self.backend.ffmpeg,media,trim,out,edits,text_resources=resources),90)
        self.assertEqual(result.returncode,0,result.stderr)
        info=validate_output(self.backend.ffprobe,out,True);validate_audio_coverage(info)
        return out

    def audio(self,path,start=0,duration=4):
        result=subprocess.run([self.backend.ffmpeg,'-v','error','-ss',str(start),'-i',str(path),'-t',str(duration),
                               '-vn','-ac','2','-ar','48000','-f','f32le','-'],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        data=array('f');data.frombytes(result.stdout);return data[::2]

    def rgb(self,path,at):
        result=subprocess.run([self.backend.ffmpeg,'-v','error','-ss',str(at),'-i',str(path),'-vf','scale=360:640',
                               '-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr);return result.stdout

    def test_precise_overlap_duck_silence_seek_and_duration(self):
        silent=replace(self.media,has_audio=False)
        edits=EditOptions(sounds=(SoundCue('comedy.boing',1,1.5),SoundCue('reveal.ding',1.1,1.5),SoundCue('cinematic.boom',1,1.5)))
        out=self.render(edits,'sounds.mp4',silent)
        audio=self.audio(out)
        self.assertLess(max(abs(v) for v in audio[:47000]),.001)
        onset=next(i for i,v in enumerate(audio) if abs(v)>.01)/48000
        self.assertAlmostEqual(onset,1,delta=.02)
        self.assertLess(max(abs(v) for v in audio),1)
        self.assertAlmostEqual(probe_media(self.backend.ffprobe,out).duration,4,delta=.04)
        # Background source + music ducking is a shared bus, with no changes to its clock.
        edits=EditOptions(sounds=(SoundCue('silence.pause',1,duration=1),SoundCue('reveal.ding',2,0,.25)))
        out=self.render(edits,'duck.mp4')
        self.assertLess(max(abs(v) for v in self.audio(out,1.2,.3)),.001)
        normal=self.audio(out,.3,.3);duck=self.audio(out,2.2,.3)
        rms=lambda x:math.sqrt(sum(v*v for v in x)/len(x))
        self.assertAlmostEqual(rms(duck)/rms(normal),.25,delta=.03)
        for at in (.3,3.3):
            samples=self.audio(out,at,.3)
            frequency=sum(a<=0<b for a,b in zip(samples,samples[1:]))/.3
            self.assertAlmostEqual(frequency,440,delta=8)
        command=audio_preview_command(self.backend.ffmpeg,self.media,2.2,TrimRange(0,4),edits=edits)
        preview=subprocess.run(command,capture_output=True,timeout=30)
        self.assertEqual(preview.returncode,0,preview.stderr)
        self.assertAlmostEqual(len(preview.stdout)/(48000*4),1.8,delta=.02)

    def test_combined_plan_gif_emoji_caption_freeze_preview_and_no_overwrite(self):
        digest=hashlib.sha256(self.source.read_bytes()).hexdigest()
        plan=starter_plan(self.media,source_identity(self.media,threading.Event()))
        plan.update(version=2,title='Comedy v2 acceptance',caption_theme='Comedy Bold',
                    timeline=[dict(kind='shot',start=0,end=1),dict(kind='freeze',source_time=1),dict(kind='shot',start=1,end=2)],
                    captions=[dict(start=1,end=2.8,text='THAT WAS PERSONAL',zone='top',basis='joke',typography={'highlight':'PERSONAL'})],
                    sfx=[dict(asset_id='comedy.boing',at=1,duck_source=.35),dict(asset_id='reveal.ding',at=1.2)],
                    overlays=[dict(kind='emoji',asset_id='emoji.skull',start=1,end=2.8,position='bottom_left',animation='pop'),
                              dict(kind='gif',asset_id=self.gif_id,start=.5,end=3.5,position='bottom_right',scale=.25,loop=True)])
        folder,assembled=assemble_plan(self.backend,self.media,plan,self.root,threading.Event())
        trim,cuts,edits=pulse_editor_state(plan,assembled)
        out=self.render(edits,'combined.mp4',assembled,trim)
        self.assertAlmostEqual(probe_media(self.backend.ffprobe,out).duration,3.8,delta=.05)
        frame=self.rgb(out,1.4);other=self.rgb(out,1.7);clean=self.rgb(assembled.path,1.4)
        # Animated lower-right GIF differs; the lower-left skull stays full colour/white.
        region=lambda data,x0,x1,y0,y1:bytes(v for y in range(y0,y1) for v in data[(y*360+x0)*3:(y*360+x1)*3])
        self.assertNotEqual(region(frame,220,330,400,500),region(other,220,330,400,500))
        self.assertGreater(sum(abs(a-b) for a,b in zip(frame,clean)),100000)
        self.assertLess(sum(abs(a-b) for a,b in zip(region(frame,0,20,360,500),region(clean,0,20,360,500)))/(20*140*3),1.5)
        # Captions remain large, and highlight creates actual yellow pixels.
        yellow=sum(1 for i in range(0,360*220*3,3) if frame[i]>170 and frame[i+1]>130 and frame[i+2]<100)
        self.assertGreater(yellow,100)
        with TextResources(edits.text) as resources:
            command=preview_command(self.backend.ffmpeg,assembled,1.4,360,640,edits,False,resources,trim,cuts)
            preview=subprocess.run(command,capture_output=True,timeout=30)
        self.assertEqual(preview.returncode,0,preview.stderr)
        ppm=preview.stdout.split(b'\n',3)[-1]
        self.assertEqual(len(ppm),len(frame))
        self.assertLess(sum(abs(a-b) for a,b in zip(ppm,frame))/len(frame),4)
        # Exclusive export refuses an already existing destination.
        original_stat=out.stat().st_mtime_ns
        original_digest=hashlib.sha256(out.read_bytes()).digest()
        with TextResources(edits.text) as resources:
            repeated=run(build_export_command(self.backend.ffmpeg,assembled,trim,out,edits,text_resources=resources),30)
        self.assertEqual(out.stat().st_mtime_ns,original_stat)
        self.assertEqual(hashlib.sha256(out.read_bytes()).digest(),original_digest)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),digest)
        if os.environ.get('PULSE_VERIFICATION_DIR'):
            target=Path(os.environ['PULSE_VERIFICATION_DIR']);target.mkdir(parents=True,exist_ok=True)
            for path in (out,self.gif,self.source):
                destination=target/path.name
                if not destination.exists():shutil.copyfile(path,destination)
            (target/'pulse-plan-v2.json').write_text(json.dumps(plan,indent=2),encoding='utf-8')
            (target/'preview.ppm').write_bytes(preview.stdout)

    def test_gif_once_opacity_rotation_and_named_effects(self):
        edits=EditOptions(overlays=(VisualCue('gif',self.gif_id,.5,3.5,loop=False,opacity=.5,rotation=30),))
        out=self.render(edits,'once.mp4')
        # After the single cycle, the overlay disappears rather than freezing its last frame.
        after=self.rgb(out,2);clean=self.rgb(self.source,2)
        self.assertLess(sum(abs(a-b) for a,b in zip(after,clean))/len(clean),1.5)
        for effect in ('punch_zoom','shake','scratch','glitch'):
            item=dict(kind='freeze',source_time=1,duration=.6,effect=effect)
            result=run(build_plan_segment_command(self.backend.ffmpeg,self.media,item,self.root/(effect+'.mp4'),'full_frame'),60)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_import_dedup_and_bad_media(self):
        library=ReactionLibrary();before=list(library.root.glob('import.*'))
        self.assertEqual(library.import_file(self.gif,'gif',self.backend.ffmpeg,self.backend.ffprobe),self.gif_id)
        self.assertEqual(list(library.root.glob('import.*')),before)
        bad=self.root/'bad.gif';bad.write_bytes(b'GIF89a broken')
        with self.assertRaises(ValueError):library.import_file(bad,'gif',self.backend.ffmpeg,self.backend.ffprobe)
        oversized=self.root/'large.gif'
        with oversized.open('wb') as stream:stream.truncate(21*1024*1024)
        with self.assertRaisesRegex(ValueError,'20 MB'):library.import_file(oversized,'gif',self.backend.ffmpeg,self.backend.ffprobe)

    def test_music_brand_cuts_speed_and_sfx_share_input_indices(self):
        from editor.music import Music, IMPORT_LABEL
        from editor.cuts import CutPlan, CutRange
        from editor.transforms import Branding
        music=ReactionLibrary().resolve('reveal.discovery')
        edits=EditOptions(speed=2,branding=Branding(True),
                          music=Music(True,IMPORT_LABEL,music,.2,.8),
                          sounds=(SoundCue('comedy.pop',.5),),
                          overlays=(VisualCue('emoji','emoji.laugh',.3,1,animation='bounce'),))
        cuts=CutPlan((CutRange(1,2),))
        with TextResources(edits.text) as resources:
            command=build_export_command(self.backend.ffmpeg,self.media,TrimRange(0,4),self.root/'all-inputs.mp4',
                                         edits,text_resources=resources,cuts=cuts)
            result=run(command,60)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertAlmostEqual(probe_media(self.backend.ffprobe,self.root/'all-inputs.mp4').duration,1.5,delta=.06)
        command=audio_preview_command(self.backend.ffmpeg,self.media,2.2,TrimRange(0,4),cuts,edits)
        result=subprocess.run(command,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
