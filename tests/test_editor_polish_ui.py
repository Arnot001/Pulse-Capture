"""Windows Tk checks for Motion, Finish, zoom focus, and Pulse Promo."""
from dataclasses import replace
import os
import unittest

from editor.models import TrimRange
from editor.privacy import Rect
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
