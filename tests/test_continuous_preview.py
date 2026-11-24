"""Continuous preview timing, cancellation and exported-frame equivalence."""
from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import Backend, run
from editor.media import probe_media
from editor.models import TrimRange
from editor.cuts import CutPlan, CutRange
from editor.transforms import EditOptions, FULL_FRAME_FORMAT
from editor.polish import Zoom, Fade
from editor.text_overlay import TextResources, TextOverlay, Caption
from editor.typography import CaptionStyle
from editor.reactions import VisualCue
from editor.ffmpeg_export import build_export_command
from editor.audio_preview import audio_preview_command
from editor.playback_preview import PlaybackPreview, playback_command, FPS, MAX_FRAMES


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS')=='1','Opt-in real FFmpeg')
class ContinuousPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name)
        cls.backend=Backend(shutil.which('ffmpeg'),shutil.which('ffprobe'),True)
        source=cls.root/'source.mp4'
        made=run([cls.backend.ffmpeg,'-v','error','-f','lavfi','-i','testsrc2=s=640x360:r=30',
                  '-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','8',
                  '-c:v','libx264','-c:a','aac',str(source)],30)
        if made.returncode:raise RuntimeError(made.stderr)
        cls.media=probe_media(cls.backend.ffprobe,source)

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_continuous_frames_use_one_process_and_restart_discards_stale_frames(self):
        playback=PlaybackPreview(self.backend.ffmpeg,self.media)
        try:
            playback.play(1,0,320,180,EditOptions(),TrimRange(0,8),CutPlan())
            seen=[];deadline=time.monotonic()+10;output=0
            while len(seen)<60 and time.monotonic()<deadline:
                frame=playback.take_due(output)
                if frame:
                    seen.append(frame);output+=1/FPS
                else:time.sleep(.003)
                self.assertFalse(playback.error,playback.error)
            self.assertEqual(len(seen),60)
            self.assertEqual(playback.process_count,1)
            self.assertLessEqual(len(playback._frames),MAX_FRAMES)
            playback.play(2,6,320,180,EditOptions(),TrimRange(0,8),CutPlan())
            deadline=time.monotonic()+5;frame=None
            while frame is None and time.monotonic()<deadline:
                frame=playback.take_due(6);time.sleep(.003)
            self.assertIsNotNone(frame,playback.error)
            self.assertEqual(frame.token,2);self.assertEqual(frame.position,6)
        finally:
            playback.close();playback._thread.join(5)
        self.assertFalse(playback._thread.is_alive())

    def test_seek_after_cut_speed_and_zoom_matches_export_with_caption_gif(self):
        trim=TrimRange(0,8);cuts=CutPlan((CutRange(2,4),))
        edits=replace(EditOptions().with_format(self.media,FULL_FRAME_FORMAT),speed=2,
            zoom=Zoom(True,1.5,mode='Zoom in',motion_speed='Full clip'),fade=Fade(True,True),
            comedy_bands=(640,360),text=TextOverlay(captions=(
                Caption(0,8,'A MOVING REACTION','Top',CaptionStyle(font_size=100,animation='pop')),)),
            overlays=(VisualCue('gif','reaction.laugh',.5,3,zone='bottom',animation='bounce'),))
        output=self.root/'edited.mp4'
        with TextResources(edits.text) as resources:
            result=run(build_export_command(self.backend.ffmpeg,self.media,trim,output,edits,text_resources=resources,cuts=cuts),90)
            self.assertEqual(result.returncode,0,result.stderr)
            # Source 5 is output 1.5 after the 2-second cut and 2x speed.
            command=playback_command(self.backend.ffmpeg,self.media,5,8,trim,cuts,edits,180,320,resources)
            result=subprocess.run(command,capture_output=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stderr)
        frame_bytes=180*320*3
        if os.environ.get('PULSE_VERIFICATION_DIR'):
            root=Path(os.environ['PULSE_VERIFICATION_DIR'])
            shutil.copyfile(output,root/'parity-export.mp4')
            (root/'stream.rgb').write_bytes(result.stdout)
        self.assertAlmostEqual(len(result.stdout)/frame_bytes,45,delta=1)
        for index in (0,9,24):
            at=1.5+index/FPS
            exported=subprocess.run([self.backend.ffmpeg,'-v','error','-ss',str(at-1/FPS),'-i',str(output),
                '-vf','scale=180:320:flags=bilinear','-frames:v','3','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,timeout=20)
            self.assertEqual(exported.returncode,0,exported.stderr)
            actual=result.stdout[index*frame_bytes:(index+1)*frame_bytes]
            self.assertEqual(len(exported.stdout),3*frame_bytes)
            # Encoder CFR rounding at a seek may choose the adjacent frame.
            # Bound it to ONE output frame and require near-identical pixels;
            # do not allow a broad image-error threshold to hide clock drift.
            matches=[sum(abs(a-b) for a,b in zip(actual,exported.stdout[j*frame_bytes:(j+1)*frame_bytes]))/frame_bytes for j in range(3)]
            difference=min(matches)
            if difference>=5 and os.environ.get('PULSE_VERIFICATION_DIR'):
                root=Path(os.environ['PULSE_VERIFICATION_DIR'])
                for name,data in (('stream',actual),('export',exported.stdout)):
                    (root/(name+'.ppm')).write_bytes(b'P6\n180 320\n255\n'+data)
                (root/'stream-command.txt').write_text(repr(command),encoding='utf-8')
            self.assertLess(difference,1,f'Preview differs by more than one output frame at {at}: {matches}')

    def test_fast_audio_seek_preserves_cut_speed_and_output_clock(self):
        from array import array
        trim=TrimRange(1,8);cuts=CutPlan((CutRange(4,6),));edits=EditOptions(speed=1.5)
        results=[]
        for fast in (False,True):
            command=audio_preview_command(self.backend.ffmpeg,self.media,3,trim,cuts,edits,seek_input=fast)
            if fast:self.assertLess(command.index('-ss'),command.index('-i'))
            result=subprocess.run(command,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            samples=array('h');samples.frombytes(result.stdout)
            results.append(samples)
        self.assertEqual(len(results[0]),len(results[1]))
        self.assertAlmostEqual(len(results[0])/(48000*2),2,delta=.02)
        error=sum(abs(a-b) for a,b in zip(*results))/len(results[0])/32768
        self.assertLess(error,.005)


if __name__=='__main__':unittest.main()
