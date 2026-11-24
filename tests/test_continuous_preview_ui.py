"""Real Tk cadence, repeated seeking, and opt-in Windows audio-clock checks."""
from dataclasses import replace
import json
import os
from pathlib import Path
import time
import unittest
from editor.cuts import CutPlan,CutRange
from editor.models import TrimRange
from editor.reactions import VisualCue
from tests import test_pulse_plan_ui as fixture


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS')=='1','Opt-in Windows Tk')
class ContinuousPreviewUITests(unittest.TestCase):
    setUp=fixture.PulsePlanUITests.setUp
    pump=fixture.PulsePlanUITests.pump

    def cleanup(self):
        playback=self.window.playback
        fixture.PulsePlanUITests.cleanup(self)
        playback._thread.join(5)
        self.assertFalse(playback._thread.is_alive())

    def test_repeated_seek_play_pause_and_frame_cadence(self):
        w=self.window;w.audio_on.set(False)
        w.cuts=CutPlan((CutRange(2,3),))
        w.edits=replace(w.edits,speed=1.5,overlays=(VisualCue('emoji','emoji.skull',0,2),))
        w.update_trim(TrimRange(0,5))
        samples=[]
        for seek in (0,3,1):
            w.seek(seek);w.play_preview()
            self.pump(lambda:not w._waiting_for_play_frame)
            times=[];previous=w.video.photo;deadline=time.monotonic()+.8
            while time.monotonic()<deadline:
                self.root.update()
                if w.video.photo is not previous:
                    times.append(time.monotonic());previous=w.video.photo
                time.sleep(.002)
            self.assertFalse(self.errors,self.errors)
            self.assertFalse(w.playback.error,w.playback.error)
            self.assertGreaterEqual(len(times),16,('Frames in 0.8s',len(times)))
            gaps=[b-a for a,b in zip(times,times[1:])]
            self.assertLess(max(gaps),.18)
            w.pause_preview();paused=w.position
            self.pump(lambda:w.video.render_context and w.video.render_context[0]==paused)
            self.assertFalse(w.playing)
            samples.append(dict(start=seek,frames=len(times),max_gap=max(gaps),paused=paused))
        if os.environ.get('PULSE_VERIFICATION_DIR'):
            (Path(os.environ['PULSE_VERIFICATION_DIR'])/'tk-cadence.json').write_text(json.dumps(samples,indent=2),encoding='utf-8')

    @unittest.skipUnless(os.environ.get('PULSE_RUN_AUDIO_DEVICE_TESTS')=='1','Opt-in real Windows output device')
    def test_real_audio_clock_tracks_picture_after_seek_and_pause(self):
        w=self.window
        if not w.media.has_audio:self.skipTest('Set PULSE_REAL_RECORDING to a recording with audio')
        w.cuts=CutPlan((CutRange(2,3),));w.edits=replace(w.edits,speed=1.5)
        w.update_trim(TrimRange(0,min(8,w.media.duration)))
        measured=[]
        for start in (0,3.5,1):
            w.seek(start);w.play_preview()
            self.pump(lambda:not w._waiting_for_play_frame and w.audio_player.elapsed() is not None)
            self.assertFalse(w.audio_player._audio_failed,w.note.cget('text'))
            self.pump(lambda:w.audio_player.elapsed()>.6)
            clock=w.audio_player.elapsed()+w.play_anchor_elapsed/w.edits.speed
            displayed=w.cuts.source_elapsed(w.video.render_context[0],w.trim)/w.edits.speed
            measured.append(abs(clock-displayed))
            self.assertLess(abs(clock-displayed),.12)
            w.pause_preview()
        if os.environ.get('PULSE_VERIFICATION_DIR'):
            (Path(os.environ['PULSE_VERIFICATION_DIR'])/'audio-picture-offsets.json').write_text(json.dumps(measured),encoding='utf-8')


if __name__=='__main__':unittest.main()
