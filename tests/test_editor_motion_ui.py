"""Tk checks for animated zoom, output-time transport and compact controls."""
from dataclasses import replace
import os
import unittest
from unittest.mock import patch
from editor.models import TrimRange
from editor.polish import Zoom, Fade
from editor.privacy import Rect
from editor.transforms import Branding
from tests import test_editor_ui as fixtures

@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1', 'Opt-in Windows Tk integration')
class MotionUITests(unittest.TestCase):
    setUp=fixtures.EditorUITests.setUp
    cleanup_ui=fixtures.EditorUITests.cleanup_ui
    pump_until=fixtures.EditorUITests.pump_until
    next_picture=fixtures.EditorUITests.next_picture

    def enable_animation(self):
        w=self.window
        self.next_picture(lambda:w.select_tool('MOTION'))
        c=w.polish_tools
        c.zoom_on.set(True);c.zoom_mode.set('Zoom in');c.zoom_motion.set('Full clip')
        self.next_picture(c.motion_changed)
        return w,c

    def test_motion_controls_states_and_minimum_layout(self):
        w=self.window;c=w.polish_tools
        w.geometry('760x700')
        self.next_picture(lambda:w.select_tool('MOTION'))
        self.assertEqual([v for v,b in c.mode_segments.buttons],['Static','Zoom in'])
        self.assertEqual([v for v,b in c.motion_segments.buttons],['Fast','Medium','Slow','Full clip'])
        self.assertTrue(all(str(b['state'])=='disabled' for v,b in c.motion_segments.buttons))
        c.zoom_on.set(True)
        self.next_picture(c.motion_changed)
        self.assertTrue(all(str(b['state'])=='disabled' for v,b in c.motion_segments.buttons))
        self.next_picture(c.mode_segments.buttons[1][1].invoke)
        self.assertTrue(all(str(b['state'])=='normal' for v,b in c.motion_segments.buttons))
        for value,button in c.speed_segments.buttons[-2:]:
            self.next_picture(button.invoke)
            self.assertEqual(w.edits.speed,float(value[:-1]))
        for value,button in c.motion_segments.buttons:
            self.next_picture(button.invoke)
            self.assertEqual(w.edits.zoom.motion_speed,value)
        def inspect(parent):
            for child in parent.winfo_children():
                if child.winfo_ismapped():
                    self.assertGreaterEqual(child.winfo_height(),child.winfo_reqheight(),str(child))
                    self.assertGreaterEqual(child.winfo_width(),child.winfo_reqwidth(),str(child))
                    inspect(child)
        inspect(w.panels['MOTION'])
        self.assertGreater(w.video.winfo_height(),120)
        self.assertGreaterEqual(w.timeline.winfo_height(),65)
        c.zoom_on.set(False);self.next_picture(c.motion_changed)
        self.assertTrue(all(str(b['state'])=='disabled' for v,b in c.motion_segments.buttons))

    def test_animated_result_autoplay_pause_resume_stop_and_state(self):
        w,c=self.enable_animation()
        w.update_trim(TrimRange(.5,3.5))
        edits,trim=w.edits,w.trim
        preview,worker=w.preview,w.preview._thread
        self.assertTrue(w.video.find_withtag('zoom'))
        with patch('editor.editor_window.Preview',side_effect=AssertionError('Extra preview')):
            self.next_picture(c.zoom_view_button.invoke)
            self.assertTrue(c.zoom_result)
            self.assertTrue(w.playing)
            self.assertFalse(w.video.find_withtag('zoom'))
            self.pump_until(lambda:w.position>.65)
            w.pause_preview();paused=w.position
            self.assertFalse(w.playing)
            old=w.video.photo
            w.request_frame();self.pump_until(lambda:w.video.photo is not old)
            self.assertEqual(w.position,paused)
            w.play_preview();self.assertEqual(w.play_anchor,paused)
            self.pump_until(lambda:w.position>paused+.05)
            self.next_picture(c.zoom_view_button.invoke)
            self.assertFalse(w.playing)
            self.assertTrue(w.video.find_withtag('zoom'))
            self.assertEqual(w.edits,edits);self.assertEqual(w.trim,trim)
        self.assertIs(w.preview,preview);self.assertIs(w.preview._thread,worker)
        self.next_picture(w.stop_preview)
        self.assertEqual(w.position,trim.start)

    def test_three_four_speed_clock_and_trim_end(self):
        w,c=self.enable_animation()
        w.update_trim(TrimRange(.5,3.5))
        for speed in (3,4):
            c.speed.set(f'{speed}.0x');self.next_picture(c.motion_changed)
            if not c.zoom_result:
                c.zoom_view_button.invoke()
            else:
                w.position=w.trim.start;w.play_preview()
            start=w.play_started
            with patch('editor.editor_window.time.monotonic',return_value=start+.125):
                w.next_frame()
                self.assertAlmostEqual(w.position,.5+.125*speed)
                w.pause_preview()
            position=w.position
            w.play_preview();self.assertEqual(w.play_anchor,position)
            with patch('editor.editor_window.time.monotonic',return_value=w.play_started+10):
                w.next_frame()
            self.assertFalse(w.playing)
            self.assertEqual(w.position,w.trim.end)
            self.next_picture(w.stop_preview)
            self.assertEqual(w.position,w.trim.start)

    def test_scrub_animation_requests_trim_relative_frames_and_tool_switch(self):
        w,c=self.enable_animation()
        w.update_trim(TrimRange(.5,3.5))
        w.format_choice.set('9:16 Vertical');self.next_picture(w.format_changed)
        c.zoom_factor.set('2x');self.next_picture(c.motion_changed)
        edits=w.edits
        self.next_picture(c.zoom_view_button.invoke)
        w.pause_preview()
        with patch.object(w.preview,'request',wraps=w.preview.request) as requests:
            for position in (.5,1.25,2):
                self.next_picture(lambda p=position:w.seek(p))
                self.assertEqual(requests.call_args.args[1],position)
                self.assertEqual(requests.call_args.args[4],edits)
                self.assertEqual(requests.call_args.args[6],w.trim)
                self.assertFalse(w.video.find_withtag('zoom'))
        for tool in ('CROP','FORMAT','MOTION'):
            self.next_picture(lambda tool=tool:w.select_tool(tool))
            self.assertEqual(w.edits,edits)
        self.next_picture(c.zoom_view_button.invoke)
        self.assertTrue(w.video.find_withtag('zoom'))
        self.assertEqual(w.edits,edits)

    def test_focus_view_keeps_fades_and_combined_edit_state(self):
        w,c=self.enable_animation()
        w.format_choice.set('9:16 Vertical');self.next_picture(w.format_changed)
        w.crop_changed(w.edits.crop.moved(w.media,80,0))
        o=w.overlay_tools
        o.input.insert('1.0','Demo');o.text_on.set(True)
        self.next_picture(o.text_changed)
        self.next_picture(lambda:o.mask_changed(Rect(200,100,80,100)))
        w.edits=replace(w.edits,branding=Branding(True),fade=Fade(True,True))
        edits=w.edits
        with patch.object(w.preview,'request',wraps=w.preview.request) as requests:
            self.next_picture(lambda:w.seek(0))
            sent=requests.call_args.args[4]
            self.assertFalse(sent.zoom.enabled)
            self.assertEqual(sent.fade,Fade())
            self.assertEqual(w.edits,edits)
            self.assertTrue(w.video.find_withtag('zoom'))
            self.next_picture(c.zoom_view_button.invoke)
            self.assertEqual(requests.call_args.args[4],edits)
            self.assertFalse(w.video.find_withtag('zoom'))
            self.next_picture(c.zoom_view_button.invoke)
            self.assertEqual(w.edits,edits)
            self.assertTrue(w.video.find_withtag('zoom'))
