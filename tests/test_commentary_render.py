"""Actual FFmpeg export + seeked audible preview of microphone commentary."""
from array import array
from dataclasses import replace
import math
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
import wave

from editor.audio_preview import audio_preview_command
from editor.commentary import CommentaryClip
from editor.ffmpeg_export import build_export_command
from editor.media import probe_media
from editor.models import TrimRange
from editor.transforms import EditOptions
from editor.cuts import CutPlan


def wav_sine(path, freq, seconds, rate=48000):
    with wave.open(str(path),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate)
        audio=array('h', (round(9500*math.sin(i*2*math.pi*freq/rate))
                          for i in range(int(seconds*rate))))
        out.writeframes(audio.tobytes())


def frequency_level(samples, frequency, at, seconds=.16, rate=48000):
    start=int(at*rate)
    samples=samples[start:start+int(seconds*rate)]
    count=len(samples)
    if not count:
        return 0
    a=sum(v*math.sin(2*math.pi*frequency*i/rate) for i,v in enumerate(samples))
    b=sum(v*math.cos(2*math.pi*frequency*i/rate) for i,v in enumerate(samples))
    return 2*math.hypot(a,b)/count


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'FFmpeg is required for real MP4 render check')
class CommentaryRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old=os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA']=self.tmp.name
        self.addCleanup(self.restore)
        root=Path(self.tmp.name)
        self.source=root/'video.mp4'
        self.output=root/'commentary.mp4'
        library=root/'Pulse Capture'/'voiceovers'
        library.mkdir(parents=True)
        self.mic=library/'recording-test.wav'
        wav_sine(self.mic,660,2.5)
        self.ffmpeg=shutil.which('ffmpeg')
        self.ffprobe=shutil.which('ffprobe')
        command=[self.ffmpeg,'-hide_banner','-loglevel','error','-nostdin','-y',
                 '-f','lavfi','-i','color=c=blue:s=320x180:r=30',
                 '-f','lavfi','-i','sine=frequency=220:sample_rate=48000',
                 '-t','4','-c:v','libx264','-pix_fmt','yuv420p',
                 '-c:a','aac','-b:a','128k',str(self.source)]
        result=subprocess.run(command,capture_output=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stderr[-1500:])
        self.media=probe_media(self.ffprobe,self.source)
        self.trim=TrimRange(0.,4.)
        self.cuts=CutPlan()
        self.cue=CommentaryClip(str(self.mic),start=1,end=2.4,
                                source_in=.4,background_gain=.2,
                                original_file=str(self.mic))
        self.edits=EditOptions(commentary_clips=(self.cue,))

    def restore(self):
        if self.old is None:os.environ.pop('LOCALAPPDATA',None)
        else:os.environ['LOCALAPPDATA']=self.old

    def _pcm(self,args):
        result=subprocess.run(args,capture_output=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stderr[-1600:])
        data=array('h');data.frombytes(result.stdout)
        return data

    def test_export_mix_ducks_original_only_during_commentary(self):
        command=build_export_command(self.ffmpeg,self.media,self.trim,
                                     self.output,self.edits,cuts=self.cuts)
        result=subprocess.run(command,capture_output=True,timeout=75)
        self.assertEqual(result.returncode,0,result.stderr[-2400:])
        self.assertTrue(self.output.is_file())
        samples=self._pcm([self.ffmpeg,'-v','error','-nostdin','-i',str(self.output),
                           '-map','0:a:0','-ar','48000','-ac','1',
                           '-c:a','pcm_s16le','-f','s16le','pipe:1'])
        self.assertAlmostEqual(len(samples)/48000,4.,delta=.12)
        base=frequency_level(samples,220,.4)
        during=frequency_level(samples,220,1.5)
        after=frequency_level(samples,220,3.1)
        vocal=frequency_level(samples,660,1.5)
        quiet=frequency_level(samples,660,.4)
        self.assertGreater(base,120)
        self.assertGreater(after,base*.6)
        self.assertLess(during,base*.65)
        self.assertGreater(vocal,quiet+250)
        self.assertEqual(self.mic.stat().st_size,240044)

    def test_video_volume_works_with_music_off_and_no_commentary(self):
        music=replace(self.edits.music,original_volume=.25)
        edits=replace(self.edits,music=music,commentary_clips=())
        self.assertFalse(edits.music.enabled)
        cmd=build_export_command(self.ffmpeg,self.media,self.trim,self.output,
                                 edits,cuts=self.cuts)
        self.assertIn('-af',cmd)
        self.assertIn('volume=0.25',cmd[cmd.index('-af')+1])
        result=subprocess.run(cmd,capture_output=True,timeout=75)
        self.assertEqual(result.returncode,0,result.stderr[-2400:])
        source=self._pcm([self.ffmpeg,'-v','error','-nostdin','-i',str(self.source),
                          '-map','0:a:0','-ac','1','-ar','48000',
                          '-c:a','pcm_s16le','-f','s16le','pipe:1'])
        output=self._pcm([self.ffmpeg,'-v','error','-nostdin','-i',str(self.output),
                          '-map','0:a:0','-ac','1','-ar','48000',
                          '-c:a','pcm_s16le','-f','s16le','pipe:1'])
        a=frequency_level(source,220,.75)
        b=frequency_level(output,220,.75)
        self.assertGreater(a,100)
        self.assertAlmostEqual(b/a,.25,delta=.055)
        preview=audio_preview_command(self.ffmpeg,self.media,0.,self.trim,
                                      self.cuts,edits)
        self.assertIn('volume=0.25',preview[preview.index('-filter_complex')+1])

    def test_disabled_auto_duck_does_not_drop_background(self):
        cue=replace(self.cue,auto_duck=False,background_gain=.05)
        edits=replace(self.edits,commentary_clips=(cue,))
        cmd=build_export_command(self.ffmpeg,self.media,self.trim,self.output,
                                 edits,cuts=self.cuts)
        result=subprocess.run(cmd,capture_output=True,timeout=75)
        self.assertEqual(result.returncode,0,result.stderr[-2400:])
        samples=self._pcm([self.ffmpeg,'-v','error','-nostdin','-i',str(self.output),
                           '-map','0:a:0','-ar','48000','-ac','1',
                           '-c:a','pcm_s16le','-f','s16le','pipe:1'])
        normal=frequency_level(samples,220,.5)
        during=frequency_level(samples,220,1.4)
        voice=frequency_level(samples,660,1.4)
        self.assertGreater(normal,100)
        self.assertGreater(during/normal,.75)
        self.assertLess(during/normal,1.25)
        self.assertGreater(voice,200)

    def test_seeked_audio_preview_keeps_original_beat_and_voice_alignment(self):
        # Listen from 1.4s: only the 1.4s+ part of the original commentary
        # is present, without replaying the opening 400 milliseconds.
        command=audio_preview_command(self.ffmpeg,self.media,1.4,
                                      self.trim,self.cuts,self.edits,seek_input=True)
        self.assertIsNotNone(command)
        samples=self._pcm(command)
        self.assertGreater(len(samples),int(1.8*48000*2))
        # Stereo PCM16 preview, select left channel.
        left=samples[::2]
        self.assertGreater(frequency_level(left,660,.10),200)
        self.assertLess(frequency_level(left,660,1.6),110)


if __name__=='__main__':
    unittest.main()
