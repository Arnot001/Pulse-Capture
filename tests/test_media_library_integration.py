"""Decode the shipped pack and measure actual audio/GIF exports, not just commands."""
from array import array
from dataclasses import replace
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import run
from editor.reaction_library import ReactionLibrary, bundled_gifs
from editor.music_library import MusicLibrary
from editor.music import Music, IMPORT_LABEL
from editor.media import probe_media
from editor.models import TrimRange
from editor.transforms import EditOptions
from editor.reactions import SoundCue, VisualCue
from editor.ffmpeg_export import build_export_command
from editor.audio_preview import audio_preview_command
from editor.preview import preview_command


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS')=='1','Opt-in real FFmpeg integration')
class MediaLibraryRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.env=patch.dict(os.environ,PULSE_REACTION_LIBRARY=str(cls.root/'reactions'));cls.env.start()
        cls.ffmpeg=shutil.which('ffmpeg');cls.probe=shutil.which('ffprobe')
        cls.source=cls.root/'source.mp4';cls.track=cls.root/'track.wav'
        for command in (
            [cls.ffmpeg,'-v','error','-f','lavfi','-i','color=c=0x203040:s=640x360:r=30',
             '-f','lavfi','-i',r"aevalsrc=0.6*sin(2*PI*400*t)*between(t\,1\,2):s=48000:d=4",'-t','4','-c:v','libx264','-c:a','aac',str(cls.source)],
            [cls.ffmpeg,'-v','error','-f','lavfi','-i',r"aevalsrc=0.4*sin(2*PI*if(lt(t\,1)\,700\,1100)*t):s=48000:d=3",'-ac','2',str(cls.track)]):
            result=run(command,30)
            if result.returncode:raise RuntimeError(result.stderr)
        cls.media=probe_media(cls.probe,cls.source)

    @classmethod
    def tearDownClass(cls):cls.env.stop();cls.temp.cleanup()

    def render(self,edits,name):
        out=self.root/name
        result=run(build_export_command(self.ffmpeg,self.media,TrimRange(0,4),out,edits),90)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertAlmostEqual(probe_media(self.probe,out).duration,4,delta=.07)
        return out

    def pcm(self,path):
        result=subprocess.run([self.ffmpeg,'-v','error','-i',str(path),'-vn','-ac','2','-ar','48000','-f','f32le','-'],capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        data=array('f');data.frombytes(result.stdout);return data[::2]

    def tone(self,data,at,frequency):
        start=round(at*48000);window=data[start:start+9600]
        return 2*abs(sum(v*complex(math.cos(i*math.tau*frequency/48000),math.sin(i*math.tau*frequency/48000)) for i,v in enumerate(window)))/len(window)

    def test_every_bundled_gif_decodes_to_changing_frames(self):
        library=ReactionLibrary()
        for key in bundled_gifs():
            result=subprocess.run([self.ffmpeg,'-v','error','-i',str(library.resolve(key)),'-t','2','-f','framemd5','-'],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,(key,result.stderr))
            hashes={line.rsplit(',',1)[-1].strip() for line in result.stdout.decode().splitlines() if line and not line.startswith('#')}
            self.assertGreater(len(hashes),2,key)

    def test_trim_loop_duck_and_seek_preview_match_actual_export(self):
        base=Music(True,IMPORT_LABEL,self.track,.8,.7,True,False,False,1,2,False)
        plain=self.pcm(self.render(EditOptions(music=base),'music-no-duck.mp4'))
        ducked=self.render(EditOptions(music=replace(base,duck_dialogue=True)),'music-duck.mp4')
        samples=self.pcm(ducked)
        self.assertGreater(self.tone(samples,.3,1100),.18)
        self.assertLess(self.tone(samples,.3,700),.01)
        self.assertLess(self.tone(samples,1.5,1100),self.tone(plain,1.5,1100)*.5)
        self.assertAlmostEqual(self.tone(samples,3.2,1100),self.tone(plain,3.2,1100),delta=.025)
        # A non-looping selection stops after exactly the selected second.
        once=self.pcm(self.render(EditOptions(music=replace(base,loop=False)),'music-once.mp4'))
        self.assertLess(self.tone(once,3,1100),.001)
        edits=EditOptions(music=replace(base,duck_dialogue=True,fade_in=True,fade_out=True))
        out=self.render(edits,'music-fades.mp4');exported=self.pcm(out)
        preview=subprocess.run(audio_preview_command(self.ffmpeg,self.media,2.8,TrimRange(0,4),edits=edits),capture_output=True,timeout=30)
        self.assertEqual(preview.returncode,0,preview.stderr)
        data=array('h');data.frombytes(preview.stdout);values=[v/32768 for v in data[::2]]
        self.assertAlmostEqual(self.tone(values,.3,1100),self.tone(exported,3.1,1100),delta=.02)

    def test_original_pack_export_has_animation_and_sound(self):
        before=hashlib.sha256(self.source.read_bytes()).digest()
        edits=EditOptions(overlays=(VisualCue('gif','reaction.facepalm',.2,3.6,x=.35,y=.25,rotation=23,scale=.4),),
                          sounds=(SoundCue('original.rimshot',.7),SoundCue('original.dog_bark',2.1,duck_source=.3)))
        out=self.render(edits,'media-pack-demo.mp4')
        frames=[]
        for at in (.4,.8):
            result=subprocess.run([self.ffmpeg,'-v','error','-ss',str(at),'-i',str(out),'-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr);frames.append(result.stdout)
        self.assertNotEqual(frames[0],frames[1])
        preview=subprocess.run(preview_command(self.ffmpeg,self.media,.8,640,360,edits,False,trim=TrimRange(0,4)),capture_output=True,timeout=30)
        self.assertEqual(preview.returncode,0,preview.stderr)
        rgb=preview.stdout.split(b'\n',3)[-1]
        self.assertLess(sum(abs(a-b) for a,b in zip(rgb,frames[1]))/len(rgb),4)
        audio=self.pcm(out)
        self.assertGreater(max(abs(v) for v in audio[34000:46000]),.1)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(),before)
        if os.environ.get('PULSE_VERIFICATION_DIR'):
            folder=Path(os.environ['PULSE_VERIFICATION_DIR']);folder.mkdir(parents=True,exist_ok=True)
            destination=folder/out.name
            if not destination.exists():shutil.copyfile(out,destination)

    def test_batch_partial_failures_dedup_metadata_and_music_records(self):
        library=ReactionLibrary()
        copied=self.root/'renamed.wav';shutil.copyfile(self.track,copied)
        bad=self.root/'bad.gif';bad.write_bytes(b'broken')
        result=library.import_many([self.track,copied,self.root/'missing.wav'],'sfx',self.ffmpeg,self.probe)
        self.assertEqual([len(result[x]) for x in ('added','duplicates','errors')],[1,1,1])
        key=result['added'][0];library.categorize([key],'My category')
        metadata=(library.root/(key+'.json')).read_bytes()
        library.import_file(copied,'sfx',self.ffmpeg,self.probe)
        self.assertEqual(metadata,(library.root/(key+'.json')).read_bytes())
        self.assertEqual(next(x for x in library.items('sfx') if x['id']==key)['category'],'My category')
        tracks=MusicLibrary(self.root/'music')
        record=dict(name='Test fixture',artist='Pulse test generator',source='Local synthesis',licence='Personal licence',requires_attribution=True,attribution='Exact fixture credit\nSecond line')
        item=tracks.save(self.track,record,self.probe)
        again=tracks.save(copied,record,self.probe)
        self.assertEqual(item['id'],again['id']);self.assertEqual(len(tracks.items()),1)
        self.assertEqual(tracks.find(tracks.path(item))['attribution'],record['attribution'])
        self.assertEqual(tracks.path(item).read_bytes(),self.track.read_bytes())


if __name__=='__main__':unittest.main()
