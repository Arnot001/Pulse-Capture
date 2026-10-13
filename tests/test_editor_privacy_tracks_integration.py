"""Actual timed privacy pixels, combined CUT renders and A/V synchronization."""
from array import array
from dataclasses import replace
import hashlib
import os
import statistics
import subprocess
import unittest
from capture.ffmpeg_backend import run, validate_output
from editor.media import probe_media
from editor.models import TrimRange
from editor.cuts import CutPlan, CutRange
from editor.polish import SPEEDS, Zoom, Fade
from editor.privacy import Privacy, PrivacyMask, Rect
from editor.transforms import EditOptions, Branding
from editor.preview import preview_command
from editor.text_overlay import TextOverlay, TextResources
from tests import test_editor_cuts_integration as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS')=='1','Opt-in real FFmpeg integration')
class PrivacyTrackExportTests(unittest.TestCase):
    setUp=fixtures.RealCutTests.setUp
    export_cut=fixtures.RealCutTests.export_cut

    def checker(self,audio):
        path=self.folder/f'checker-{audio}.mp4'
        pattern="nullsrc=s=320x240:r=30,geq=lum='if(mod(floor(X/4)+floor(Y/4),2),235,16)':cb=128:cr=128"
        cmd=[self.ffmpeg,'-v','error','-f','lavfi','-i',pattern]
        if audio:
            cmd+=['-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-c:a','aac']
        cmd+=['-t','8','-c:v','libx264','-crf','10','-pix_fmt','yuv420p',str(path)]
        result=run(cmd,30);self.assertEqual(result.returncode,0,result.stderr)
        return probe_media(self.probe,path)

    def pixels(self,path,t,width=320,height=240):
        result=subprocess.run([self.ffmpeg,'-v','error','-ss',str(t),'-i',str(path),'-frames:v','1',
                               '-pix_fmt','rgb24','-f','rawvideo','-'],capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(result.stdout),width*height*3)
        return result.stdout

    def preview_pixels(self,media,edits,trim,cuts,position):
        width,height=edits.output_size(media)
        with TextResources(edits.text) as resources:
            cmd=preview_command(self.ffmpeg,media,position,width,height,edits,False,resources,trim,cuts)
            cmd[cmd.index('ppm')]='rawvideo';cmd[cmd.index('image2pipe')]='rawvideo'
            cmd[-1:-1]=['-pix_fmt','rgb24']
            result=subprocess.run(cmd,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(len(result.stdout),width*height*3)
        return result.stdout

    def assert_protected(self,pixels,x,y,active):
        sample=[pixels[(row*320+col)*3] for row in range(y,y+16) for col in range(x,x+16)]
        if active:
            self.assertLess(statistics.pstdev(sample),35)
        else:
            self.assertGreater(statistics.pstdev(sample),80)

    def test_multiple_mixed_overlapping_masks_every_speed_audio_and_silence(self):
        trim=TrimRange(.5,7.5)
        cuts=CutPlan((CutRange(2,3),CutRange(5,5.5)))
        for audio in (False,True):
            media=self.checker(audio);digest=hashlib.sha256(media.path.read_bytes()).digest()
            for speed in SPEEDS:
                masks=(PrivacyMask('Blur',Rect(40,40,100,80),1,4),
                       PrivacyMask('Pixelate',Rect(90,70,100,90),3.5,6),
                       PrivacyMask('Blur',Rect(220,150,80,80),6.2,7))
                edits=EditOptions(privacy=Privacy(masks),speed=speed)
                with self.subTest(audio=audio,speed=speed):
                    path=self.export_cut(media,trim,cuts,edits)
                    for position in (.75,1.5,3.75,4.5,5.8,6.5,7.25):
                        elapsed=cuts.source_elapsed(position,trim)/speed
                        pixels=self.pixels(path,elapsed)
                        for mask,(x,y) in zip(masks,((55,50),(150,120),(240,170))):
                            self.assert_protected(pixels,x,y,mask.active(position))
                        if speed in (.5,4) and position in (1.5,3.75,6.5):
                            preview=self.preview_pixels(media,edits,trim,cuts,position)
                            self.assertLess(sum(abs(a-b) for a,b in zip(pixels,preview))/len(pixels),10)
            self.assertEqual(hashlib.sha256(media.path.read_bytes()).digest(),digest)
        self.assertFalse(list(self.folder.glob('*.partial.mp4')))
        self.assertFalse(list(self.folder.glob('*.lock')))

    def test_multiple_same_mode_without_cuts_and_excluded_intervals(self):
        media=self.checker(False)
        for mode in ('Blur','Pixelate'):
            masks=(PrivacyMask(mode,Rect(40,40,100,80),1,3),
                   PrivacyMask(mode,Rect(90,70,100,90),2,4),
                   PrivacyMask(mode,Rect(220,150,80,80),6,7))
            trim=TrimRange(2,5)
            edits=EditOptions(privacy=Privacy(masks))
            path=self.export_cut(media,trim,CutPlan(),edits)
            for position in (2.5,3.5,4.5):
                pixels=self.pixels(path,position-trim.start)
                for mask,(x,y) in zip(masks,((55,50),(150,120),(240,170))):
                    self.assert_protected(pixels,x,y,mask.active(position))
            # An entire source interval can disappear in CUT with no residual effect.
            cut=CutPlan((CutRange(1,4),))
            path=self.export_cut(media,TrimRange(0,5),cut,edits)
            pixels=self.pixels(path,1.2)
            self.assert_protected(pixels,55,50,False)
            self.assert_protected(pixels,150,120,False)

    def test_maximum_pipeline_preview_agreement_crop_and_duration(self):
        media=self.checker(True)
        digest=hashlib.sha256(media.path.read_bytes()).digest()
        trim=TrimRange(.5,7.5);cuts=CutPlan((CutRange(2,3),CutRange(5,5.5)))
        privacy=Privacy((PrivacyMask('Blur',Rect(100,50,100,80),1,4),
                         PrivacyMask('Pixelate',Rect(140,80,80,100),3.5,6.8),
                         PrivacyMask('Blur',Rect(0,0,20,20),0,8)))
        for speed in (1,3,4):
            edits=EditOptions(privacy=privacy,zoom=Zoom(True,1.5,.6,.4,'Zoom in','Full clip'),
                              text=TextOverlay(True,'PRIVATE'),branding=Branding(True),
                              speed=speed,fade=Fade(True,True)).with_format(media,'9:16 Vertical')
            edits=replace(edits,crop=edits.crop.moved(media,100,0))
            path=self.export_cut(media,trim,cuts,edits)
            width,height=edits.output_size(media)
            for t in (.2,.6,1.0):
                pixels=self.pixels(path,t,width,height)
                # The existing CFR speed conversion may retain the preceding
                # output frame. Bound the comparison to one output frame, rather
                # than raising pixel tolerance on this high-frequency pattern.
                sample_times=(t,) if speed==1 else (t, t-1/media.fps)
                errors=[]
                for sample_time in sample_times:
                    position=cuts.source_from_elapsed(sample_time*speed,trim)
                    preview=self.preview_pixels(media,edits,trim,cuts,position)
                    errors.append(sum(abs(a-b) for a,b in zip(pixels,preview))/len(pixels))
                self.assertLess(min(errors),18,(speed,t,errors))
            info=validate_output(self.probe,path,True)
            streams=info['streams']
            vd=float(next(s for s in streams if s['codec_type']=='video')['duration'])
            ad=float(next(s for s in streams if s['codec_type']=='audio')['duration'])
            self.assertLess(abs(vd-ad),.12)
        self.assertEqual(hashlib.sha256(media.path.read_bytes()).digest(),digest)
        self.assertFalse(list(self.folder.glob('*.partial.mp4')))
        self.assertFalse(list(self.folder.glob('*.lock')))

    def test_audio_flash_sync_with_cut_and_timed_privacy(self):
        path=self.folder/'sync.mp4'
        result=run([self.ffmpeg,'-v','error','-f','lavfi','-i',
            "color=c=gray:size=320x240:rate=30,drawbox=color=white:t=fill:enable='between(t,3,4)'",
            '-f','lavfi','-i',"sine=frequency=440:sample_rate=48000,volume='between(t,3,4)':eval=frame",
            '-t','6','-c:v','libx264','-c:a','aac',str(path)],30)
        self.assertEqual(result.returncode,0,result.stderr)
        media=probe_media(self.probe,path);trim=TrimRange(.5,5.5);cuts=CutPlan((CutRange(1,2),))
        privacy=Privacy((PrivacyMask('Blur',Rect(30,30,60,60),.7,3.5),
                         PrivacyMask('Pixelate',Rect(50,50,60,60),3,5)))
        for speed in (1,3,4):
            edits=EditOptions(privacy=privacy,speed=speed,fade=Fade(True,True))
            output=self.export_cut(media,trim,cuts,edits)
            result=subprocess.run([self.ffmpeg,'-v','error','-i',str(output),'-vn','-ac','1',
                '-ar','48000','-f','f32le','-'],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            samples=array('f');samples.frombytes(result.stdout)
            blocks=[sum(v*v for v in samples[i:i+480])/480 for i in range(0,len(samples)-479,480)]
            onset=next(i for i,v in enumerate(blocks) if v>max(blocks)*.1)*.01
            self.assertAlmostEqual(onset,1.5/speed,delta=.07)
            pixels=subprocess.run([self.ffmpeg,'-v','error','-i',str(output),'-vf','crop=40:40:220:160,scale=1:1',
                                   '-pix_fmt','gray','-f','rawvideo','-'],capture_output=True,timeout=15)
            self.assertEqual(pixels.returncode,0,pixels.stderr)
            flash=next(i for i,v in enumerate(pixels.stdout) if v>190)/30
            self.assertAlmostEqual(flash,onset,delta=.09)

    def test_cancel_multiple_masks_keeps_source_and_cleans_export(self):
        import threading
        from editor.export_job import ExportJob
        media=self.checker(True)
        digest=hashlib.sha256(media.path.read_bytes()).digest()
        edits=EditOptions(privacy=Privacy((PrivacyMask('Blur',Rect(40,40,100,80),1,4),
                                          PrivacyMask('Pixelate',Rect(90,70,100,90),3,6))),
                          text=TextOverlay(True,'Private'))
        started=threading.Event();children=[]
        def launch(cmd,**kwargs):
            cmd.insert(cmd.index('-i'),'-re')
            child=subprocess.Popen(cmd,**kwargs);children.append(child);started.set()
            return child
        job=ExportJob(self.backend,popen=launch)
        job.start(media,TrimRange(0,8),edits=edits,cuts=CutPlan((CutRange(2,3),)))
        self.assertTrue(started.wait(5));job.cancel()
        self.assertTrue(job.wait(10))
        self.assertEqual(list(job.events.queue)[-1].kind,'cancelled')
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(hashlib.sha256(media.path.read_bytes()).digest(),digest)
        self.assertEqual(list(self.folder.iterdir()),[media.path])
