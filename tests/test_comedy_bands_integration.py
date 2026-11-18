"""Real 12-second FFmpeg acceptance: full frame, bands, imports, cuts and speed."""
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import Backend, run, validate_output, validate_audio_coverage
from editor.media import probe_media
from editor.models import TrimRange
from editor.cuts import CutPlan, CutRange
from editor.transforms import EditOptions, FULL_FRAME_FORMAT
from editor.text_overlay import TextOverlay, TextResources, Caption
from editor.typography import CaptionStyle
from editor.reaction_library import ReactionLibrary
from editor.reactions import SoundCue, VisualCue
from editor.ffmpeg_export import build_export_command, build_plan_segment_command
from editor.preview import preview_command
from tests import test_comedy_v2_integration as fixture


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS')=='1','Opt-in real FFmpeg integration')
class ComedyBandsRenderTests(unittest.TestCase):
    audio=fixture.ComedyRenderTests.audio
    rgb=fixture.ComedyRenderTests.rgb

    def test_full_clip_metadata_cuts_speed_bands_gif_and_preview(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ,PULSE_REACTION_LIBRARY=temporary+'/library'):
            self.root=Path(temporary)
            self.backend=Backend(shutil.which('ffmpeg'),shutil.which('ffprobe'),True)
            source=self.root/'landscape.mp4'
            result=run([self.backend.ffmpeg,'-v','error','-nostdin','-n','-f','lavfi','-i',
                'color=c=0x204060:s=640x360:r=30,drawbox=x=0:y=0:w=30:h=360:c=red:t=fill,drawbox=x=610:y=0:w=30:h=360:c=lime:t=fill',
                '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','28','-c:v','libx264','-c:a','aac',str(source)],60)
            self.assertEqual(result.returncode,0,result.stderr)
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            media=probe_media(self.backend.ffprobe,source)
            reaction=self.root/'original-reaction.wav'
            result=run([self.backend.ffmpeg,'-v','error','-nostdin','-n','-f','lavfi','-i',
                'sine=frequency=1200:sample_rate=48000','-t','3','-metadata','title=Original test reaction',
                '-metadata','artist=Pulse test fixture','-metadata','copyright=Original generated test tone',str(reaction)],30)
            self.assertEqual(result.returncode,0,result.stderr)
            library=ReactionLibrary()
            key=library.import_file(reaction,'sfx',self.backend.ffmpeg,self.backend.ffprobe)
            self.assertEqual(library.metadata(key)['name'],'Original test reaction')
            self.assertEqual(library.metadata(key)['artist'],'Pulse test fixture')
            library.update_details(key,dict(name='Ain’t no way',transcript='Aw nah brooo',licence='Original test fixture',attribution='Exact supplied credit'))
            library.categorize([key],'Disbelief');library.remember(key,True)
            library.resolve(key).unlink()  # Controlled missing-file recovery in a temporary library.
            library.import_file(reaction,'sfx',self.backend.ffmpeg,self.backend.ffprobe)
            recreated=ReactionLibrary()
            self.assertEqual(recreated.metadata(key)['attribution'],'Exact supplied credit')
            self.assertEqual(recreated.metadata(key)['transcript'],'Aw nah brooo')
            self.assertEqual(recreated.preferences()['categories'][key],'Disbelief')
            self.assertIn(key,recreated.preferences()['favourites'])
            self.assertEqual(recreated.import_many([reaction,reaction],'sfx',self.backend.ffmpeg,self.backend.ffprobe)['duplicates'],[key,key])
            edits=replace(EditOptions().with_format(media,FULL_FRAME_FORMAT),speed=2,comedy_bands=(640,360),
                text=TextOverlay(captions=(Caption(0,28,'BRO REALLY SAID\nFUCK THE MISSION','Top',CaptionStyle(font_size=104,animation='none')),
                    Caption(0,28,'DOGGO\nCOMES FIRST','Bottom',CaptionStyle(font_size=104,band_width=.70,alignment='left',animation='none')))),
                sounds=(SoundCue(key,2,duck_source=.25),),
                overlays=(VisualCue('emoji','emoji.skull',0,12,zone='bottom',x=1,y=.5,scale=.16),
                          VisualCue('gif','reaction.laugh',6,11,zone='top',x=1,y=1,scale=.1,animation='bounce')))
            cuts=CutPlan((CutRange(4,8),));trim=TrimRange(0,28)
            output=self.root/'comedy-bands-12s.mp4'
            with TextResources(edits.text) as resources:
                result=run(build_export_command(self.backend.ffmpeg,media,trim,output,edits,text_resources=resources,cuts=cuts),120)
                self.assertEqual(result.returncode,0,result.stderr)
                # Output 3.4 s is source 10.8 s after the cut and 2x speed.
                preview=subprocess.run(preview_command(self.backend.ffmpeg,media,10.8,360,640,edits,False,resources,trim,cuts),capture_output=True,timeout=30)
                gif_preview=subprocess.run(preview_command(self.backend.ffmpeg,media,19.6,360,640,edits,False,resources,trim,cuts),capture_output=True,timeout=30)
            self.assertEqual(preview.returncode,0,preview.stderr)
            info=validate_output(self.backend.ffprobe,output,True);validate_audio_coverage(info)
            self.assertAlmostEqual(probe_media(self.backend.ffprobe,output).duration,12,delta=.05)
            frame=self.rgb(output,3.4);ppm=preview.stdout.split(b'\n',3)[-1]
            self.assertEqual(len(frame),len(ppm))
            self.assertLess(sum(abs(a-b) for a,b in zip(frame,ppm))/len(frame),4)
            self.assertEqual(gif_preview.returncode,0,gif_preview.stderr)
            gif_frame=self.rgb(output,7.8)
            gif_ppm=gif_preview.stdout.split(b'\n',3)[-1]
            self.assertLess(sum(abs(a-b) for a,b in zip(gif_frame,gif_ppm))/len(gif_frame),4)
            pixel=lambda x,y:frame[(y*360+x)*3:(y*360+x)*3+3]
            self.assertGreater(pixel(5,320)[0],180)  # Left landscape edge survives.
            self.assertGreater(pixel(355,320)[1],180)  # Right edge survives.
            # Compare output with no overlays: all changed pixels stay out of gameplay.
            clean=replace(edits,text=TextOverlay(),overlays=())
            before=subprocess.run(preview_command(self.backend.ffmpeg,media,10.8,360,640,clean,False,None,trim,cuts),capture_output=True,timeout=30)
            self.assertEqual(before.returncode,0,before.stderr)
            base=before.stdout.split(b'\n',3)[-1]
            centre=slice(220*360*3,420*360*3)
            self.assertLess(sum(abs(a-b) for a,b in zip(frame[centre],base[centre]))/(200*360*3),2)
            for low,high in ((55,200),(435,525)):
                self.assertGreater(sum(abs(a-b) for a,b in zip(frame[low*1080:high*1080],base[low*1080:high*1080])),100000)
            rms=lambda data:math.sqrt(sum(x*x for x in data)/len(data))
            # A 1200 Hz reaction is still audible 2.6 seconds after insertion (old UI cut at 1.8).
            samples=self.audio(output,4.6,.2)
            magnitude=lambda frequency:abs(sum(x*complex(math.cos(2*math.pi*frequency*i/48000),math.sin(2*math.pi*frequency*i/48000)) for i,x in enumerate(samples)))/len(samples)
            self.assertGreater(magnitude(1200),.025)
            self.assertLess(magnitude(440),.02)
            self.assertGreater(rms(self.audio(output,1,.2)),.04)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),digest)
            for effect in ('punch_zoom','shake','scratch','glitch'):
                segment=self.root/(effect+'.mp4')
                result=run(build_plan_segment_command(self.backend.ffmpeg,media,
                    dict(kind='freeze',source_time=1,duration=.6,effect=effect),segment,'comedy_bands'),60)
                self.assertEqual(result.returncode,0,result.stderr)
                effect_frame=self.rgb(segment,.1)
                self.assertLess(max(effect_frame[60*1080:150*1080]),45)  # Effect never touches top band.
            if os.environ.get('PULSE_VERIFICATION_DIR'):
                target=Path(os.environ['PULSE_VERIFICATION_DIR']);target.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(output,target/output.name)
                (target/'comedy-bands-preview.ppm').write_bytes(preview.stdout)


if __name__=='__main__':unittest.main()
