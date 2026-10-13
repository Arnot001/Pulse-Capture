"""Real animated zoom exports, image agreement, audio pitch and sync."""
from array import array
from dataclasses import replace
import hashlib
import json
import os
import subprocess
import unittest
from capture.ffmpeg_backend import run, validate_output
from editor.media import probe_media
from editor.models import TrimRange
from editor.polish import Zoom, Fade, SPEEDS, ZOOM_TIMINGS, animation_duration
from editor.privacy import PrivacyMask, Privacy, Rect
from editor.preview import preview_command
from editor.text_overlay import TextOverlay, TextResources
from editor.transforms import EditOptions, Branding, FORMATS
from tests import test_editor_polish_integration as fixtures

@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS') == '1', 'Opt-in real FFmpeg integration')
class AnimatedExportTests(unittest.TestCase):
    setUp = fixtures.RealPolishTests.setUp
    source = fixtures.RealPolishTests.source
    export_polished = fixtures.RealPolishTests.export_polished

    def decode(self, path):
        result=run([self.ffmpeg,'-v','error','-i',str(path),'-f','null','-'],30)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_animation_formats_speeds_audio_and_motion_timings(self):
        for audio in (False,True):
            media=self.source(audio)
            for i,speed in enumerate(SPEEDS):
                preset=list(FORMATS)[i%4]
                motion=list(ZOOM_TIMINGS)[i%4]
                edits=EditOptions(zoom=Zoom(True, (1.25,1.5,2)[i%3], i%2, (i//2)%2,
                    'Zoom in',motion),speed=speed).with_format(media,preset)
                if edits.crop:
                    edits=replace(edits,crop=edits.crop.moved(media,50,20))
                with self.subTest(audio=audio,speed=speed,preset=preset,motion=motion):
                    self.decode(self.export_polished(media,edits))

    def test_start_mid_end_pixels_agree_with_preview(self):
        # A static pattern isolates motion geometry from frame-selection effects.
        path=self.folder/'pattern.mp4'
        result=run([self.ffmpeg,'-v','error','-f','lavfi','-i',
            'testsrc2=size=640x480:rate=30,trim=end_frame=1,loop=loop=-1:size=1:start=0',
            '-t','7','-c:v','libx264','-pix_fmt','yuv420p',str(path)],30)
        self.assertEqual(result.returncode,0,result.stderr)
        media=probe_media(self.probe,path)
        trim=TrimRange(.5,6.5)
        for speed,label in ((1,'Fast'),(3,'Medium'),(4,'Slow'),(.5,'Full clip'),(1,'Full clip'),(3,'Full clip'),(4,'Full clip')):
            edits=EditOptions(zoom=Zoom(True,2,.7,.3,'Zoom in',label),speed=speed).with_format(media,'9:16 Vertical')
            edits=replace(edits,crop=edits.crop.moved(media,100,0))
            output=self.export_polished(media,edits,trim)
            seconds=animation_duration(edits.zoom,trim.duration,speed,media.fps)
            width,height=edits.output_size(media)
            frame_info=subprocess.run([self.probe,'-v','error','-select_streams','v:0',
                '-show_entries','frame=best_effort_timestamp_time','-of','json',str(output)],
                capture_output=True,timeout=15)
            self.assertEqual(frame_info.returncode,0,frame_info.stderr)
            timestamps=[float(f['best_effort_timestamp_time']) for f in json.loads(frame_info.stdout)['frames']]
            frames=[]
            for wanted in (0,seconds/2,seconds):
                # Use actual encoded timestamps and frame indexes, not a rounded
                # seek at EOF. The exact duration boundary has no encoded frame.
                index=min(range(len(timestamps)),key=lambda i:abs(timestamps[i]-wanted))
                t=timestamps[index]
                decoded=subprocess.run([self.ffmpeg,'-v','error','-i',str(output),
                    '-vf',f"select='eq(n,{index})'",'-frames:v','1','-pix_fmt','rgb24',
                    '-f','rawvideo','-'],capture_output=True,timeout=15)
                self.assertEqual(decoded.returncode,0,decoded.stderr)
                cmd=preview_command(self.ffmpeg,media,trim.start+t*speed,width,height,edits,False,trim=trim)
                cmd[cmd.index('ppm')]='rawvideo'
                cmd[cmd.index('image2pipe')]='rawvideo'
                cmd[-1:-1]=['-pix_fmt','rgb24']
                preview=subprocess.run(cmd,capture_output=True,timeout=15)
                self.assertEqual(preview.returncode,0,preview.stderr)
                self.assertEqual(len(decoded.stdout),width*height*3)
                self.assertEqual(len(preview.stdout),len(decoded.stdout))
                error=sum(abs(a-b) for a,b in zip(decoded.stdout,preview.stdout))/len(preview.stdout)
                self.assertLess(error,14,(speed,label,t,error))
                frames.append(decoded.stdout)
            self.assertGreater(sum(abs(a-b) for a,b in zip(frames[0],frames[-1]))/len(frames[0]),20)

    def test_odd_source_and_one_frame_short_clip(self):
        path=self.folder/'odd.mkv'
        result=run([self.ffmpeg,'-v','error','-f','lavfi','-i','testsrc=size=321x241:rate=30',
                    '-t','1','-c:v','ffv1',str(path)],30)
        self.assertEqual(result.returncode,0,result.stderr)
        media=probe_media(self.probe,path)
        for trim in (TrimRange(0,1/30),TrimRange(.1,.5)):
            for speed in (1,4):
                edits=EditOptions(zoom=Zoom(True,2,1,1,'Zoom in','Full clip'),speed=speed)
                with self.subTest(trim=trim,speed=speed):
                    self.decode(self.export_polished(media,edits,trim))

    def test_maximum_combination_audio_sync_pitch_and_cleanup(self):
        # The same one-second visual flash and audible tone permit a real A/V
        # timing comparison after trim and 3x/4x; 440 Hz should remain 440 Hz.
        path=self.folder/'sync.mp4'
        result=run([self.ffmpeg,'-v','error','-f','lavfi','-i',
            "color=c=gray:size=640x480:rate=30,drawbox=color=white:t=fill:enable='between(t,2,3)'",
            '-f','lavfi','-i',"sine=frequency=440:sample_rate=48000,volume='between(t,2,3)':eval=frame",
            '-t','6','-c:v','libx264','-c:a','aac',str(path)],30)
        self.assertEqual(result.returncode,0,result.stderr)
        media=probe_media(self.probe,path)
        digest=hashlib.sha256(path.read_bytes()).digest()
        for speed in (3,4):
            edits=EditOptions(privacy=Privacy((PrivacyMask('Pixelate', Rect(160,100,100,100), 0, media.duration),)),
                text=TextOverlay(True,'PULSE DEMO'),branding=Branding(True,'Bottom right','Medium'),
                zoom=Zoom(True,1.5,.6,.3,'Zoom in','Full clip'),speed=speed,fade=Fade(True,True)
                ).with_format(media,'9:16 Vertical')
            edits=replace(edits,crop=edits.crop.moved(media,100,0))
            output=self.export_polished(media,edits,TrimRange(.5,5.5))
            self.decode(output)
            width,height=edits.output_size(media)
            with TextResources(edits.text) as resources:
                for t in (0, .2, .8):
                    preview_cmd=preview_command(self.ffmpeg,media,.5+t*speed,width,height,
                        edits,False,resources,TrimRange(.5,5.5))
                    preview_cmd[preview_cmd.index('ppm')]='rawvideo'
                    preview_cmd[preview_cmd.index('image2pipe')]='rawvideo'
                    preview_cmd[-1:-1]=['-pix_fmt','rgb24']
                    preview=subprocess.run(preview_cmd,capture_output=True,timeout=15)
                    decoded=subprocess.run([self.ffmpeg,'-v','error','-ss',str(t),'-i',str(output),
                        '-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,timeout=15)
                    self.assertEqual(preview.returncode,0,preview.stderr)
                    self.assertEqual(decoded.returncode,0,decoded.stderr)
                    self.assertEqual(len(preview.stdout),len(decoded.stdout))
                    self.assertGreater(len(preview.stdout),0)
                    error=sum(abs(a-b) for a,b in zip(preview.stdout,decoded.stdout))/len(preview.stdout)
                    self.assertLess(error,14,(speed,t,error))
            info=validate_output(self.probe,output,True)
            streams=info['streams']
            vd=float(next(s for s in streams if s['codec_type']=='video')['duration'])
            ad=float(next(s for s in streams if s['codec_type']=='audio')['duration'])
            self.assertLess(abs(vd-ad),.12)
            audio=subprocess.run([self.ffmpeg,'-v','error','-i',str(output),'-vn','-ac','1',
                '-ar','48000','-f','f32le','-'],capture_output=True,timeout=15)
            self.assertEqual(audio.returncode,0,audio.stderr)
            samples=array('f');samples.frombytes(audio.stdout)
            blocks=[sum(v*v for v in samples[i:i+480])/480 for i in range(0,len(samples)-479,480)]
            threshold=max(blocks)*.1
            onset=next(i for i,v in enumerate(blocks) if v>threshold)*.01
            self.assertAlmostEqual(onset,1.5/speed,delta=.07)
            section=samples[round((onset+.06)*48000):round((onset+.15)*48000)]
            crossings=sum(a<=0<b for a,b in zip(section,section[1:]))
            self.assertAlmostEqual(crossings/(len(section)/48000),440,delta=25)
            pixels=subprocess.run([self.ffmpeg,'-v','error','-i',str(output),'-vf',
                'crop=40:40:80:100,scale=1:1','-pix_fmt','gray','-f','rawvideo','-'],
                capture_output=True,timeout=15)
            self.assertEqual(pixels.returncode,0,pixels.stderr)
            flash=next(i for i,v in enumerate(pixels.stdout) if v>190)/30
            self.assertAlmostEqual(flash,onset,delta=.09)
        self.assertEqual(hashlib.sha256(path.read_bytes()).digest(),digest)
        self.assertFalse(list(self.folder.glob('*.partial.mp4')))
        self.assertFalse(list(self.folder.glob('*.lock')))
