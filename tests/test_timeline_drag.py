"""New timeline click/drag/edge-stretch smoke tests; no audio/device needed."""
from types import SimpleNamespace
import unittest
from editor.timeline import Timeline


class DummyTimeline:
    TRACK_TOP=Timeline.TRACK_TOP
    TRACK_HEIGHT=Timeline.TRACK_HEIGHT
    TRACK_LABELS=Timeline.TRACK_LABELS
    visible_span=Timeline.visible_span
    block_x=Timeline.block_x
    block_seconds=Timeline.block_seconds
    block_hit=Timeline.block_hit
    begin=Timeline.begin
    move=Timeline.move
    release=Timeline.release
    zoom_wheel=Timeline.zoom_wheel
    def __init__(self):
        self.media=SimpleNamespace(duration=30,fps=60)
        self.trim=SimpleNamespace(start=0,end=30)
        self.output_duration=30
        self.view_start=0
        self.view_span=0
        self.enabled=True
        self.drag=None
        self.clip_drag=None
        self.clip_blocks=(SimpleNamespace(kind='overlay',index=0,key=('overlay',0),
                           track=2,start=5,end=15,label='emoji.skull'),)
        self.changed=[]
        self.begun=[]
        self.ended=0
        self.on_clip_begin=self.begun.append
        self.on_clip_change=lambda *args:self.changed.append(args)
        self.on_clip_end=lambda:setattr(self,'ended',self.ended+1)
        self.on_seek=lambda value:None
        self.on_trim=lambda *args:None
        self.draw=lambda:None
    def winfo_width(self):return 628
    def seconds(self,x):return x/20
    def x(self,seconds):return seconds*20

class TimelinePointerTests(unittest.TestCase):
    def event(self,x,y):return SimpleNamespace(x=x,y=y)
    def test_middle_move_preserves_duration(self):
        w=DummyTimeline()
        y=w.TRACK_TOP+2*w.TRACK_HEIGHT+12
        w.begin(self.event(w.block_x(10),y))
        w.move(self.event(w.block_x(13),y))
        self.assertEqual(w.changed[-1][0],('overlay',0))
        self.assertAlmostEqual(w.changed[-1][1],8)
        self.assertAlmostEqual(w.changed[-1][2],18)
        w.release(self.event(0,0))
        self.assertEqual(w.ended,1)
    def test_left_and_right_handles_resize(self):
        w=DummyTimeline();y=w.TRACK_TOP+2*w.TRACK_HEIGHT+12
        w.begin(self.event(w.block_x(5)+1,y))
        w.move(self.event(w.block_x(7),y))
        self.assertAlmostEqual(w.changed[-1][1],7)
        self.assertAlmostEqual(w.changed[-1][2],15)
        w.release(self.event(0,0))
        w.begin(self.event(w.block_x(15)-1,y))
        w.move(self.event(w.block_x(18),y))
        self.assertAlmostEqual(w.changed[-1][1],5)
        self.assertAlmostEqual(w.changed[-1][2],18)
    def test_clamped_at_end(self):
        w=DummyTimeline();y=w.TRACK_TOP+2*w.TRACK_HEIGHT+12
        w.begin(self.event(w.block_x(10),y))
        w.move(self.event(w.block_x(28),y))
        self.assertAlmostEqual(w.changed[-1][1],20)
        self.assertAlmostEqual(w.changed[-1][2],30)
    def test_mousewheel_zoom_gives_precision_for_long_recordings(self):
        w=DummyTimeline()
        w.output_duration=300
        w.zoom_wheel(self.event(310,100).__class__(x=310,y=100,delta=120))
        self.assertLess(w.visible_span(),300)
        self.assertGreaterEqual(w.view_start,0)
        for _ in range(25):w.zoom_wheel(SimpleNamespace(x=310,delta=120))
        self.assertAlmostEqual(w.visible_span(),2)

    def test_click_on_empty_output_track_seeks(self):
        w=DummyTimeline();values=[]
        w.on_output_seek=values.append
        w.begin(self.event(w.block_x(12),w.TRACK_TOP+5*w.TRACK_HEIGHT+8))
        self.assertAlmostEqual(values[-1],12)

if __name__=='__main__':unittest.main()
