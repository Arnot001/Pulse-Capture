"""New timeline click/drag/edge-stretch smoke tests; no audio/device needed."""
from types import SimpleNamespace
import unittest
from editor.timeline import Timeline


class FakeDeleteMenu:
    def __init__(self):
        self.opened=[]
        self.released=0
    def tk_popup(self,x,y):
        self.opened.append((x,y))
    def grab_release(self):
        self.released+=1


class DummyTimeline:
    TRACK_TOP=Timeline.TRACK_TOP
    TRACK_HEIGHT=Timeline.TRACK_HEIGHT
    TRACK_LABELS=Timeline.TRACK_LABELS
    MOVEABLE=Timeline.MOVEABLE
    DELETABLE=Timeline.DELETABLE
    block_at=Timeline.block_at
    right_click=Timeline.right_click
    delete_selected=Timeline.delete_selected
    clear_selection=Timeline.clear_selection
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
        self.selected_key=None
        self._delete_menu=FakeDeleteMenu()
        self.focus_calls=0
        self.deleted=[]
        self.on_clip_delete=self.deleted.append
        self.drag=None
        self.clip_drag=None
        self.clip_blocks=(SimpleNamespace(kind='overlay',index=0,key=('overlay',0),
                           track=3,start=5,end=15,label='emoji.skull'),)
        self.changed=[]
        self.begun=[]
        self.ended=0
        self.on_clip_begin=self.begun.append
        self.on_clip_change=lambda *args:self.changed.append(args)
        self.on_clip_end=lambda:setattr(self,'ended',self.ended+1)
        self.on_seek=lambda value:None
        self.on_trim=lambda *args:None
        self.draw=lambda:None
    def focus_set(self):self.focus_calls+=1
    def winfo_width(self):return 628
    def seconds(self,x):return x/20
    def x(self,seconds):return seconds*20

class TimelinePointerTests(unittest.TestCase):
    def event(self,x,y):return SimpleNamespace(x=x,y=y)
    def test_right_click_photo_and_emoji_deletes_selected_item(self):
        w=DummyTimeline()
        w.clip_blocks=(
            SimpleNamespace(kind='media',index=0,key=('media',0),track=1,start=4,end=10,label='photo'),
            SimpleNamespace(kind='overlay',index=0,key=('overlay',0),track=3,start=5,end=15,label='emoji'))
        for track,key,time in ((1,('media',0),6),(3,('overlay',0),8)):
            e=SimpleNamespace(x=w.block_x(time),y=w.TRACK_TOP+track*w.TRACK_HEIGHT+12,
                              x_root=80,y_root=120)
            self.assertEqual(w.right_click(e),'break')
            self.assertEqual(w.selected_key,key)
            self.assertEqual(w.delete_selected(),'break')
            self.assertEqual(w.deleted[-1],key)
        self.assertEqual(w._delete_menu.opened,[(80,120),(80,120)])
        self.assertEqual(w._delete_menu.released,2)
        self.assertEqual(w.focus_calls,2)

    def test_delete_key_only_works_for_selected_timeline_block(self):
        w=DummyTimeline()
        self.assertEqual(w.delete_selected(),'break')
        self.assertEqual(w.deleted,[])
        y=w.TRACK_TOP+3*w.TRACK_HEIGHT+12
        w.begin(self.event(w.block_x(10),y))
        self.assertEqual(w.selected_key,('overlay',0))
        self.assertEqual(w.delete_selected(),'break')
        self.assertEqual(w.deleted,[('overlay',0)])
        self.assertEqual(w.clear_selection(),'break')
        w.delete_selected()
        self.assertEqual(len(w.deleted),1)

    def test_blank_right_click_and_original_video_cannot_be_deleted(self):
        w=DummyTimeline()
        w.clip_blocks+=(SimpleNamespace(kind='video',index=0,key=('video',0),
                                        track=0,start=0,end=30,label='original'),)
        for track in (0,7):
            e=SimpleNamespace(x=w.block_x(10),y=w.TRACK_TOP+track*w.TRACK_HEIGHT+12,
                              x_root=12,y_root=50)
            w.right_click(e)
        self.assertEqual(w._delete_menu.opened,[])
        self.assertEqual(w.deleted,[])

    def test_crop_key_marker_takes_priority_over_full_zoom(self):
        w=DummyTimeline()
        w.clip_blocks=(
            SimpleNamespace(kind='crop_key',index=0,key=('crop_key',0),
                            track=7,start=10,end=10,label='Crop'),
            SimpleNamespace(kind='zoom',index=0,key=('zoom',0),
                            track=7,start=0,end=30,label='Zoom'))
        hit=w.block_at(w.block_x(10),w.TRACK_TOP+7*w.TRACK_HEIGHT+9,w.DELETABLE)
        self.assertEqual(hit.key,('crop_key',0))
        other=w.block_at(w.block_x(14),w.TRACK_TOP+7*w.TRACK_HEIGHT+9,w.DELETABLE)
        self.assertEqual(other.key,('zoom',0))

    def test_disabled_timeline_blocks_context_deletion(self):
        w=DummyTimeline()
        w.enabled=False
        w.selected_key=('overlay',0)
        e=SimpleNamespace(x=w.block_x(10),y=w.TRACK_TOP+3*w.TRACK_HEIGHT+12,
                          x_root=4,y_root=4)
        w.right_click(e)
        w.delete_selected()
        self.assertEqual(w._delete_menu.opened,[])
        self.assertEqual(w.deleted,[])

    def test_middle_move_preserves_duration(self):
        w=DummyTimeline()
        y=w.TRACK_TOP+3*w.TRACK_HEIGHT+12
        w.begin(self.event(w.block_x(10),y))
        w.move(self.event(w.block_x(13),y))
        self.assertEqual(w.changed[-1][0],('overlay',0))
        self.assertAlmostEqual(w.changed[-1][1],8)
        self.assertAlmostEqual(w.changed[-1][2],18)
        w.release(self.event(0,0))
        self.assertEqual(w.ended,1)
    def test_left_and_right_handles_resize(self):
        w=DummyTimeline();y=w.TRACK_TOP+3*w.TRACK_HEIGHT+12
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
        w=DummyTimeline();y=w.TRACK_TOP+3*w.TRACK_HEIGHT+12
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
