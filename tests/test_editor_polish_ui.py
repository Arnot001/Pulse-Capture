"""Windows Tk checks for Motion, Finish, zoom focus, and Pulse Promo."""
from dataclasses import replace
import os
import subprocess
import tkinter as tk
import unittest
from unittest.mock import patch

from editor.models import TrimRange
from editor.privacy import Rect
from editor.transforms import Branding
from editor.polish import Fade, Zoom
from tests import test_editor_ui as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1', 'Opt-in Windows Tk integration')
class PolishUITests(unittest.TestCase):
    setUp = fixtures.EditorUITests.setUp
    cleanup_ui = fixtures.EditorUITests.cleanup_ui
    pump_until = fixtures.EditorUITests.pump_until
    next_picture = fixtures.EditorUITests.next_picture

    def test_all_eight_panels_fit_minimum_window(self):
        w = self.window
        w.geometry('760x700')
        self.root.update()
        for name in ('TRIM', 'FORMAT', 'CROP', 'BRAND', 'TEXT', 'PRIVACY', 'MOTION', 'FINISH'):
            self.next_picture(lambda name=name: w.select_tool(name))
            self.assertGreater(w.video.winfo_height(), 110)
            self.assertGreaterEqual(w.timeline.winfo_height(), 65)
            panel = w.panels[name]
            def inspect(parent):
                for child in parent.winfo_children():
                    if child.winfo_ismapped():
                        self.assertLessEqual(child.winfo_y()+child.winfo_height(), parent.winfo_height()+1,
                                             f'{name}: {child}')
                        self.assertLessEqual(child.winfo_x()+child.winfo_width(), parent.winfo_width()+1,
                                             f'{name}: {child}')
                        inspect(child)
            inspect(panel)
            if name == 'MOTION':
                for control in (w.polish_tools.zoom_view_button, w.polish_tools.motion_hint):
                    self.assertGreaterEqual(control.winfo_height(), control.winfo_reqheight())
                    self.assertGreaterEqual(control.winfo_width(), control.winfo_reqwidth())

    def test_zoom_focus_speed_and_preview(self):
        w = self.window
        w.format_choice.set('9:16 Vertical')
        self.next_picture(w.format_changed)
        self.next_picture(lambda: w.select_tool('MOTION'))
        w.polish_tools.zoom_on.set(True)
        w.polish_tools.zoom_factor.set('2x')
        self.next_picture(w.polish_tools.motion_changed)
        self.assertTrue(w.edits.zoom.enabled)
        self.assertTrue(w.video.zoom_active)
        self.assertTrue(w.video.find_withtag('zoom'))

        left, top, width, height = w.video.bounds()
        before = (w.edits.zoom.focus_x, w.edits.zoom.focus_y)
        old_photo = w.video.photo
        w.video.event_generate('<Button-1>', x=round(left+width*.75), y=round(top+height*.35))
        w.video.event_generate('<ButtonRelease-1>')
        self.pump_until(lambda: w.video.photo is not old_photo)
        after = (w.edits.zoom.focus_x, w.edits.zoom.focus_y)
        self.assertNotEqual(before, after)
        self.assertGreater(after[0], .5)

        w.polish_tools.speed.set('2.0x')
        self.next_picture(w.polish_tools.motion_changed)
        self.assertEqual(w.edits.speed, 2.0)
        self.next_picture(lambda: w.select_tool('FORMAT'))
        self.assertFalse(w.video.zoom_active)
        self.assertLess(w.video.photo.width(), w.video.photo.height())

    def test_zoom_view_initial_off_on_and_reset(self):
        w = self.window
        controls = w.polish_tools
        self.next_picture(lambda: w.select_tool('MOTION'))
        button = controls.zoom_view_button
        self.assertTrue(button.winfo_ismapped())
        self.assertEqual(button.cget('text'), 'VIEW ZOOM RESULT')
        self.assertEqual(str(button.cget('state')), 'disabled')
        self.assertFalse(controls.zoom_result)
        token = w.token
        button.invoke()
        controls.toggle_zoom_view()  # Also guard direct callbacks while Zoom is off.
        self.assertFalse(controls.zoom_result)
        self.assertEqual(w.token, token)
        self.assertFalse(w.video.find_withtag('zoom'))

        controls.zoom_on.set(True)
        self.next_picture(controls.motion_changed)
        self.assertEqual(str(button.cget('state')), 'normal')
        self.assertTrue(w.video.find_withtag('zoom'))
        self.next_picture(button.invoke)
        self.assertTrue(controls.zoom_result)
        self.assertEqual(button.cget('text'), 'EDIT ZOOM FOCUS')
        controls.zoom_on.set(False)
        self.next_picture(controls.motion_changed)
        self.assertFalse(controls.zoom_result)
        self.assertFalse(w.video.display_zoomed)
        self.assertEqual(str(button.cget('state')), 'disabled')
        self.assertEqual(button.cget('text'), 'VIEW ZOOM RESULT')
        controls.zoom_on.set(True)
        self.next_picture(controls.motion_changed)
        self.assertFalse(controls.zoom_result)
        self.assertTrue(w.video.find_withtag('zoom'))
        w.set_busy(True)
        self.assertEqual(str(button.cget('state')), 'disabled')
        w.set_busy(False)
        self.assertEqual(str(button.cget('state')), 'normal')

    def test_zoom_view_preserves_edits_and_matches_combined_export(self):
        w = self.window
        controls = w.polish_tools
        w.update_trim(TrimRange(.5, 2.5))
        self.next_picture(lambda: w.seek(.5))
        w.format_choice.set('9:16 Vertical')
        self.next_picture(w.format_changed)
        w.crop_changed(w.edits.crop.moved(w.media, 120, 0))
        overlay = w.overlay_tools
        overlay.input.insert('1.0', 'Pulse demo')
        overlay.text_on.set(True)
        self.next_picture(overlay.text_changed)
        self.next_picture(lambda: overlay.mask_changed(Rect(200, 100, 100, 100)))
        w.edits = replace(w.edits, branding=Branding(True, 'Bottom right', 'Medium'))
        controls.zoom_on.set(True)
        controls.zoom_factor.set('1.5x')
        controls.speed.set('1.5x')
        self.next_picture(controls.motion_changed)
        self.next_picture(lambda: w.select_tool('MOTION'))
        left, top, width, height = w.video.bounds()
        old = w.video.photo
        w.video.event_generate('<Button-1>', x=round(left+width*.6), y=round(top+height*.4))
        w.video.event_generate('<B1-Motion>', x=round(left+width*.7), y=round(top+height*.3))
        w.video.event_generate('<ButtonRelease-1>')
        self.pump_until(lambda: w.video.photo is not old)
        edits, trim = w.edits, w.trim
        self.assertTrue(w.video.find_withtag('zoom'))
        with patch.object(w.preview, 'request', wraps=w.preview.request) as requests:
            self.next_picture(controls.zoom_view_button.invoke)
            self.assertEqual(requests.call_args.args[4], edits)
            self.assertFalse(requests.call_args.args[5])
        self.assertEqual(w.tool.get(), 'MOTION')
        self.assertEqual(w.edits, edits)
        self.assertEqual(w.trim, trim)
        self.assertTrue(w.video.display_zoomed)
        self.assertFalse(w.video.zoom_active)
        self.assertFalse(w.video.find_withtag('zoom'))
        # Neither canvas gestures nor direct focus callbacks may edit result mode.
        w.video.event_generate('<Button-1>', x=round(left), y=round(top))
        w.video.event_generate('<B1-Motion>', x=round(left+width), y=round(top+height))
        w.video.event_generate('<ButtonRelease-1>')
        controls.focus_changed(.1, .1)
        self.assertEqual(w.edits, edits)
        result_photo = w.video.photo
        w.export()
        self.pump_until(lambda: w.last_export is not None, timeout=30)
        self.assertEqual(w.edits, edits)
        self.assertEqual(w.trim, trim)
        # Compare the actual Motion result with the first exported frame (same
        # source time), including crop, privacy, text, brand, zoom and speed.
        frame = subprocess.run([
            self.ffmpeg, '-v', 'error', '-i', str(w.last_export), '-frames:v', '1',
            '-vf', f'scale={result_photo.width()}:{result_photo.height()}',
            '-c:v', 'ppm', '-f', 'image2pipe', '-'], capture_output=True, timeout=15)
        self.assertEqual(frame.returncode, 0, frame.stderr)
        exported = tk.PhotoImage(master=w, data=frame.stdout, format='PPM')
        differences = []
        for y in range(0, exported.height(), 5):
            for x in range(0, exported.width(), 5):
                differences.extend(abs(a-b) for a, b in zip(exported.get(x, y), result_photo.get(x, y)))
        self.assertLess(sum(differences)/len(differences), 18)

        with patch.object(w.preview, 'request', wraps=w.preview.request) as requests:
            # Before the full frame arrives, the old zoomed image must not be
            # clickable as though it were the full frame.
            controls.zoom_view_button.invoke()
            self.assertFalse(w.video.zoom_ready())
            self.assertFalse(w.video.find_withtag('zoom'))
            self.pump_until(lambda: w.video.photo is not result_photo)
            sent = requests.call_args.args[4]
            self.assertEqual(sent, replace(edits, zoom=replace(edits.zoom, enabled=False)))
        self.assertFalse(controls.zoom_result)
        self.assertFalse(w.video.display_zoomed)
        self.assertTrue(w.video.find_withtag('zoom'))
        self.assertEqual(w.edits, edits)
        self.assertEqual(w.trim, trim)

    def test_zoom_view_factors_tools_and_single_preview_worker(self):
        w = self.window
        controls = w.polish_tools
        controls.zoom_on.set(True)
        self.next_picture(controls.motion_changed)
        self.next_picture(lambda: w.select_tool('MOTION'))
        preview, worker = w.preview, w.preview._thread
        children = []
        popen = subprocess.Popen
        def tracked_popen(*args, **kwargs):
            self.assertTrue(all(child.poll() is not None for child in children))
            child = popen(*args, **kwargs)
            children.append(child)
            return child
        with patch('editor.editor_window.Preview', side_effect=AssertionError('Duplicate preview worker')):
            with patch('editor.preview.subprocess.Popen', side_effect=tracked_popen):
                for factor in ('1.25x', '1.5x', '2x'):
                    controls.zoom_factor.set(factor)
                    self.next_picture(controls.motion_changed)
                    self.assertFalse(w.video.display_zoomed)
                    edits = w.edits
                    self.next_picture(controls.zoom_view_button.invoke)
                    self.assertTrue(w.video.display_zoomed)
                    for tool in ('FORMAT', 'CROP', 'MOTION'):
                        self.next_picture(lambda tool=tool: w.select_tool(tool))
                        self.assertEqual(w.edits, edits)
                        self.assertTrue(controls.zoom_result)
                    self.assertFalse(w.video.find_withtag('zoom'))
                    self.next_picture(controls.zoom_view_button.invoke)
                    self.assertTrue(w.video.find_withtag('zoom'))
                # Rapid toggles coalesce through the existing latest-request queue.
                old = w.video.photo
                for _ in range(12):
                    controls.zoom_view_button.invoke()
                self.pump_until(lambda: w.video.photo is not old)
        self.assertGreater(len(children), 0)
        self.assertIs(w.preview, preview)
        self.assertIs(w.preview._thread, worker)
        self.assertTrue(worker.is_alive())
        self.assertFalse(controls.zoom_result)
        self.assertFalse(w.video.display_zoomed)
        self.assertTrue(all(child.poll() is not None for child in children))

    def test_zoom_result_transport_and_minimum_layout(self):
        w = self.window
        controls = w.polish_tools
        w.geometry('760x700')
        self.next_picture(lambda: w.select_tool('MOTION'))
        controls.zoom_on.set(True)
        self.next_picture(controls.motion_changed)
        self.next_picture(controls.zoom_view_button.invoke)
        button = controls.zoom_view_button
        self.assertEqual(button.cget('text'), 'EDIT ZOOM FOCUS')
        self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
        self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
        parent = button.master
        self.assertLessEqual(button.winfo_y()+button.winfo_height(), parent.winfo_height())
        self.assertLessEqual(parent.winfo_y()+parent.winfo_height(), parent.master.winfo_height())
        self.assertGreater(w.video.winfo_height(), 110)
        self.assertGreaterEqual(w.timeline.winfo_height(), 65)
        w.update_trim(TrimRange(.5, 2.5))
        self.next_picture(lambda: w.seek(.5))
        w.play_preview()
        self.pump_until(lambda: w.position > .6)
        w.pause_preview()
        paused = w.position
        self.assertFalse(w.playing)
        self.assertTrue(controls.zoom_result)
        w.play_preview()
        self.assertAlmostEqual(w.play_anchor, paused, delta=.03)
        self.next_picture(controls.zoom_view_button.invoke)
        self.assertFalse(w.playing)
        self.assertIsNone(w._play_id)
        self.assertFalse(controls.zoom_result)
        w.stop_preview()
        self.assertAlmostEqual(w.position, .5, places=2)

    def test_pulse_promo_preserves_trim_text_privacy_and_exports(self):
        w = self.window
        w.update_trim(TrimRange(.5, 2.5))
        controls = w.overlay_tools
        controls.input.delete('1.0', 'end')
        controls.input.insert('1.0', 'Pulse demo')
        controls.text_on.set(True)
        self.next_picture(controls.text_changed)
        mask = Rect(180, 120, 120, 100)
        self.next_picture(lambda: controls.mask_changed(mask))

        w.polish_tools.zoom_on.set(True)
        w.polish_tools.zoom_factor.set('1.5x')
        w.polish_tools.speed.set('2.0x')
        self.next_picture(w.polish_tools.motion_changed)
        self.next_picture(lambda: w.select_tool('FINISH'))
        w.polish_tools.apply_promo()
        self.pump_until(lambda: w.video.photo is not None)

        self.assertEqual(w.edits.preset, '9:16 Vertical')
        self.assertTrue(w.edits.branding.enabled)
        self.assertEqual(w.edits.branding.position, 'Bottom right')
        self.assertEqual(w.edits.branding.size, 'Medium')
        self.assertEqual(w.edits.speed, 1.0)
        self.assertFalse(w.edits.zoom.enabled)
        self.assertEqual(w.edits.fade, Fade(True, True))
        self.assertTrue(w.edits.text.enabled)
        self.assertEqual(w.edits.privacy.mask, mask)
        self.assertEqual(w.trim, TrimRange(.5, 2.5))

        w.export()
        self.pump_until(lambda: w.last_export is not None, timeout=30)
        self.assertTrue(w.last_export.is_file())
        self.assertIn('EXPORTED', w.note.cget('text'))


if __name__ == '__main__':
    unittest.main()
