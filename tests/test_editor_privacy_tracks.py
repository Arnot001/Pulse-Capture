"""Source-time privacy state, cut mapping and render-clock contracts."""
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import unittest
from editor.models import MediaInfo, TrimRange
from editor.cuts import CutPlan, CutRange
from editor.privacy import Privacy, PrivacyMask, Rect, mask_intervals, output_mask
from editor.polish import SPEEDS, Zoom, Fade
from editor.transforms import EditOptions, Branding
from editor.ffmpeg_export import build_export_command
from editor.preview import preview_command
from editor.text_overlay import TextOverlay, TextResources


class PrivacyTrackTests(unittest.TestCase):
    def setUp(self):
        self.media=MediaInfo(Path('source.mp4'),30,640,480,30,True)
        self.rect=Rect(200,100,100,80)
        self.mask=PrivacyMask('Blur',self.rect,8,18)
        self.trim=TrimRange(0,30)
        self.cuts=CutPlan((CutRange(10,15),))

    def test_empty_single_and_stable_overlapping_collection(self):
        Privacy().validate(self.media)
        a=replace(self.mask,start=20,end=25)
        b=replace(self.mask,mode='Pixelate',start=19,end=26)
        masks=(a,b,a)  # deliberate insertion order, spatial/time overlap, no merging
        privacy=Privacy(masks)
        privacy.validate(self.media)
        self.assertEqual(privacy.masks,masks)
        self.assertEqual(privacy.active_masks(21),masks)
        self.assertEqual(privacy.active_masks(18),())
        self.assertEqual(Privacy((a,)).active_masks(20),(a,))
        self.assertEqual(Privacy((a,)).active_masks(25),())
        with self.assertRaises(FrozenInstanceError):
            a.start=0

    def test_invalid_modes_rectangles_collections_and_times(self):
        for changes in ({'mode':'Track'},{'rect':None},{'rect':Rect(-1,0,20,20)},
                        {'start':True},{'start':'1'},{'start':float('nan')},
                        {'end':float('inf')},{'start':-1},{'end':31},
                        {'start':18},{'start':19},{'start':8,'end':8.001}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                replace(self.mask,**changes).validate(self.media)
        for value in ([self.mask],('invalid',)):
            with self.assertRaises(ValueError):
                Privacy(value).validate(self.media)

    def test_tiny_media_one_frame_is_valid(self):
        media=replace(self.media,duration=.01)
        PrivacyMask('Blur',self.rect,0,.01).validate(media)
        self.assertEqual(mask_intervals(PrivacyMask('Blur',self.rect,0,.01),TrimRange(0,.01),speed=4),
                         (TrimRange(0,.0025),))

    def test_requested_cut_examples(self):
        mask=replace(self.mask,start=20,end=25)
        self.assertEqual(mask_intervals(mask,self.trim,self.cuts),(TrimRange(15,20),))
        self.assertEqual(mask_intervals(self.mask,self.trim,self.cuts),(TrimRange(8,10),TrimRange(10,13)))
        self.assertEqual(self.mask.start,8)
        self.assertEqual(self.mask.end,18)

    def test_partial_trim_and_fully_trimmed_out(self):
        mask=replace(self.mask,start=5,end=10)
        self.assertEqual(mask_intervals(mask,TrimRange(7,20)),(TrimRange(0,3),))
        self.assertEqual(mask_intervals(mask,TrimRange(10,20)),())
        self.assertEqual(mask_intervals(mask,TrimRange(0,5)),())

    def test_cut_fully_removes_interval(self):
        mask=replace(self.mask,start=11,end=14)
        self.assertEqual(mask_intervals(mask,self.trim,self.cuts),())

    def test_one_mask_split_by_multiple_cuts(self):
        cuts=CutPlan((CutRange(10,12),CutRange(14,16)))
        expected=(TrimRange(8,10),TrimRange(10,12),TrimRange(12,14))
        self.assertEqual(mask_intervals(self.mask,self.trim,cuts),expected)
        self.assertEqual(sum(r.duration for r in expected),6)

    def test_every_speed_mapping(self):
        for speed in SPEEDS:
            actual=mask_intervals(self.mask,self.trim,self.cuts,speed)
            self.assertEqual(actual,(TrimRange(8/speed,10/speed),TrimRange(10/speed,13/speed)))
        with self.assertRaises(ValueError):
            mask_intervals(self.mask,self.trim,speed=0)

    def test_independent_crop_clipping_preserves_state(self):
        masks=(self.mask,replace(self.mask,rect=Rect(0,0,20,20)),
               replace(self.mask,rect=Rect(200,100,100,80)))
        edits=EditOptions(privacy=Privacy(masks)).with_format(self.media,'9:16 Vertical')
        edits=replace(edits,crop=edits.crop.moved(self.media,250,0))
        self.assertEqual(output_mask(masks[0].rect,self.media,edits.crop),Rect(0,100,50,80))
        self.assertIsNone(output_mask(masks[1].rect,self.media,edits.crop))
        self.assertEqual(edits.privacy.masks,masks)

    def test_sequential_unique_labels_and_pre_speed_clock(self):
        masks=(replace(self.mask,start=8,end=18),replace(self.mask,mode='Pixelate',start=20,end=25))
        for speed in SPEEDS:
            edits=EditOptions(privacy=Privacy(masks),zoom=Zoom(True,mode='Zoom in',motion_speed='Full clip'),
                              text=TextOverlay(True,'Private'),branding=Branding(True),speed=speed,fade=Fade(True,True))
            with TextResources(edits.text) as resources:
                cmd=build_export_command('ffmpeg',self.media,self.trim,'out.mp4',edits,text_resources=resources,cuts=self.cuts)
            graph=cmd[cmd.index('-filter_complex')+1]
            self.assertIn("enable='gte(t,8.000000000)*lt(t,10.000000000)+gte(t,10.000000000)*lt(t,13.000000000)'",graph)
            self.assertIn("enable='gte(t,15.000000000)*lt(t,20.000000000)'",graph)
            markers=['concat=', '[cutv]pad=', '[private0]format=', '[private1]setpts=', 'zoompan=', 'drawtext=', '[text][wm]overlay=', 'fade=t=in']
            self.assertEqual([graph.index(v) for v in markers],sorted(graph.index(v) for v in markers))
            self.assertEqual(graph.count('[private0_hidden]'),2)
            self.assertEqual(graph.count('[private1_hidden]'),2)
            self.assertIn('-n',cmd)
            self.assertNotIn('-y',cmd)

    def test_preview_source_time_before_during_after_and_overlap(self):
        masks=(replace(self.mask,start=5,end=10),replace(self.mask,mode='Pixelate',start=8,end=12))
        edits=EditOptions(privacy=Privacy(masks),speed=4)
        for position,blur,pixelate in ((4,False,False),(5,True,False),(9,True,True),(10,False,True),(12,False,False)):
            cmd=preview_command('ffmpeg',self.media,position,320,240,edits,False,trim=self.trim,cuts=self.cuts)
            self.assertEqual('gblur=' in ' '.join(cmd),blur)
            self.assertEqual('flags=neighbor' in ' '.join(cmd),pixelate)
            self.assertNotIn("enable=",' '.join(cmd))

    def test_removed_masks_add_no_effect_and_source_overwrite_rejected(self):
        edits=EditOptions(privacy=Privacy((replace(self.mask,start=11,end=14),)))
        cmd=build_export_command('ffmpeg',self.media,self.trim,'out.mp4',edits,cuts=self.cuts)
        self.assertNotIn('gblur=', ' '.join(cmd))
        with self.assertRaises(ValueError):
            build_export_command('ffmpeg',self.media,self.trim,self.media.path,edits,cuts=self.cuts)

    def test_source_scrubbing_still_shows_masks_excluded_from_export(self):
        edits=EditOptions(privacy=Privacy((replace(self.mask,start=11,end=14),)))
        for trim in (self.trim,TrimRange(20,30)):
            cmd=preview_command('ffmpeg',self.media,12,320,240,edits,False,trim=trim,cuts=self.cuts)
            self.assertIn('gblur=', ' '.join(cmd))
            cmd=build_export_command('ffmpeg',self.media,trim,'out.mp4',edits,cuts=self.cuts)
            self.assertNotIn('gblur=', ' '.join(cmd))
