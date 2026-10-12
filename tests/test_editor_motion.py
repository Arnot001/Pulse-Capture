"""Output-time zoom and conservative tempo-chain regression checks."""
from dataclasses import replace
from pathlib import Path
import math
import unittest
from editor.models import MediaInfo, TrimRange
from editor.polish import (SPEEDS, ZOOM_TIMINGS, Zoom, Fade, animated_geometry,
    animation_duration, animation_progress, audio_tempo_filters, zoom_filter, zoom_geometry)
from editor.transforms import EditOptions, FORMATS
from editor.ffmpeg_export import build_export_command
from editor.preview import preview_command

class MotionMathTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 20, 1920, 1080, 30, True)
        self.zoom = Zoom(True, 2, .8, .2, 'Zoom in', 'Slow')

    def test_all_speeds_duration_and_safe_audio_chains(self):
        self.assertEqual(SPEEDS, (.5, 1, 1.5, 2, 3, 4))
        for speed in SPEEDS:
            self.assertAlmostEqual(EditOptions(speed=speed).output_duration(12), 12/speed)
            chain = audio_tempo_filters(speed)
            stages = [float(stage.split('=')[1]) for stage in chain]
            self.assertAlmostEqual(math.prod(stages), speed)
            self.assertTrue(all(.5 <= value <= 2 for value in stages))
        self.assertEqual(audio_tempo_filters(3), ['atempo=1.5', 'atempo=2'])
        self.assertEqual(audio_tempo_filters(4), ['atempo=2', 'atempo=2'])

    def test_invalid_speed_mode_motion_and_timing(self):
        for speed in (0, -1, .75, 2.5, 5, True, float('nan'), float('inf')):
            with self.subTest(speed=speed), self.assertRaises(ValueError):
                audio_tempo_filters(speed)
        for zoom in (replace(self.zoom, mode='Zoom out'), replace(self.zoom, motion_speed='Quick')):
            with self.assertRaises(ValueError):
                zoom.validate()
        for time, seconds in ((float('nan'), 1), (1, 0), (1, float('inf'))):
            with self.assertRaises(ValueError):
                animation_progress(time, seconds)

    def test_static_filter_and_geometry_unchanged(self):
        zoom = Zoom(True, 2)
        self.assertEqual(zoom_geometry(self.media, None, zoom), (480,270,960,540,1920,1080))
        self.assertEqual(zoom_filter(self.media, None, zoom, 4, 10, .2),
                         'crop=960:540:480:270,scale=1920:1080:flags=lanczos')

    def test_start_midpoint_end_and_clamping(self):
        for factor in (1.25, 1.5, 2):
            zoom = replace(self.zoom, factor=factor)
            for time, expected in ((-1,1), (0,1), (1.75,(1+factor)/2), (3.5,factor), (100,factor)):
                x,y,width,height,bw,bh = animated_geometry(self.media, None, zoom, time, 20, 1)
                self.assertAlmostEqual(bw/width, expected)
                self.assertAlmostEqual(bh/height, expected)
                self.assertTrue(0 <= x <= bw-width and 0 <= y <= bh-height)
        self.assertEqual(animation_progress(.375, 1.5), .15625)

    def test_all_edge_focus_shifted_formats_and_odd_dimensions(self):
        media = replace(self.media, width=1365, height=767)
        for preset in FORMATS:
            edits = EditOptions().with_format(media, preset)
            crop = edits.crop.moved(media, 50, 20) if edits.crop else None
            for fx,fy in ((0,0),(0,1),(1,0),(1,1)):
                for time in (0,.4,1.5):
                    z = replace(self.zoom, focus_x=fx, focus_y=fy)
                    x,y,w,h,bw,bh = animated_geometry(media,crop,z,time,20,1)
                    self.assertTrue(0 <= x <= bw-w and 0 <= y <= bh-h)
                    self.assertEqual((bw%2,bh%2),(0,0))
                    self.assertAlmostEqual(w/h,bw/bh)

    def test_motion_seconds_independent_of_clip_speed(self):
        for label, seconds in ZOOM_TIMINGS.items():
            if seconds is None:
                continue
            zoom = replace(self.zoom, motion_speed=label)
            for speed in SPEEDS:
                self.assertEqual(animation_duration(zoom,20,speed,30), seconds)
                self.assertEqual(animated_geometry(self.media,None,zoom,seconds/2,20,speed),
                                 animated_geometry(self.media,None,zoom,seconds/2,20,1))
                self.assertIn(f'in_time/{speed:g}', zoom_filter(self.media,None,zoom,speed,20))

    def test_short_clip_and_fade_duration(self):
        for speed in SPEEDS:
            self.assertGreater(animation_duration(self.zoom, 1/30, speed, 30), 0)
            self.assertTrue(all(math.isfinite(v) for v in animated_geometry(
                self.media,None,self.zoom,0,1/30,speed)))
        edits = EditOptions(zoom=self.zoom,speed=4,fade=Fade(True,True))
        cmd = build_export_command('ffmpeg',self.media,TrimRange(1,1.4),'out.mp4',edits)
        graph=cmd[cmd.index('-filter_complex')+1]
        self.assertIn('fade=t=out:st=0.050000:d=0.050000',graph)
        self.assertLess(graph.index('zoompan='),graph.index('setpts=PTS/4'))
        self.assertLess(graph.index('setpts=PTS/4'),graph.index('fade=t=in'))
        self.assertIn('atempo=2,atempo=2',cmd[cmd.index('-af')+1])

    def test_preview_uses_trim_relative_output_time(self):
        edits = EditOptions(zoom=self.zoom,speed=4)
        cmd = preview_command('ffmpeg',self.media,5.6,320,240,edits,False,trim=TrimRange(4,16))
        graph=cmd[cmd.index('-filter_complex')+1]
        self.assertIn('(0.400000000)',graph)
        self.assertNotIn('in_time/',graph)
        self.assertNotIn('setpts=PTS/4',graph)

    def test_new_presets_and_full_clip_exact_output_duration(self):
        self.assertEqual(ZOOM_TIMINGS, {'Fast': .6, 'Medium': 1.5, 'Slow': 3.5, 'Full clip': None})
        zoom = replace(self.zoom, motion_speed='Full clip')
        for speed in (.5, 1, 3, 4):
            duration = 12/speed
            self.assertEqual(animation_duration(zoom,12,speed,30),duration)
            for time, factor in ((-1,1),(0,1),(duration/2,1.5),(duration,2),(duration+1,2)):
                geometry = animated_geometry(self.media,None,zoom,time,12,speed)
                self.assertAlmostEqual(geometry[4]/geometry[2],factor)
            self.assertLess(animation_progress(duration-1/30,duration),1)
        self.assertEqual(animation_duration(zoom,12,3,30),4)

    def test_full_clip_shifted_crop_edges_odd_and_tiny(self):
        media=replace(self.media,width=1365,height=767)
        crop=EditOptions().with_format(media,'9:16 Vertical').crop.moved(media,50,20)
        for speed in (.5,1,3,4):
            for length in (1/30,.1,12):
                for fx,fy in ((0,0),(0,1),(1,0),(1,1)):
                    zoom=Zoom(True,2,fx,fy,'Zoom in','Full clip')
                    duration=animation_duration(zoom,length,speed,30)
                    self.assertEqual(duration,length/speed)
                    for t in (0,duration/2,duration):
                        x,y,w,h,bw,bh=animated_geometry(media,crop,zoom,t,length,speed)
                        self.assertTrue(all(math.isfinite(v) for v in (x,y,w,h)))
                        self.assertTrue(0<=x<=bw-w and 0<=y<=bh-h)
                        self.assertAlmostEqual(w/h,bw/bh)

    def test_full_clip_preview_at_source_end_uses_exact_endpoint(self):
        edits=EditOptions(zoom=replace(self.zoom,motion_speed='Full clip'),speed=3)
        cmd=preview_command('ffmpeg',self.media,20,320,240,edits,False,trim=TrimRange(8,20))
        graph=cmd[cmd.index('-filter_complex')+1]
        self.assertIn('(4.000000000)/4.000000000',graph)
        self.assertLess(float(cmd[cmd.index('-ss')+1]),20)
