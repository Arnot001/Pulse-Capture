"""Actual Tk text/privacy interaction and layout regression checks."""
import os
import subprocess
import unittest
from editor.privacy import Rect, output_mask
from tests import test_editor_ui as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1', 'Opt-in Windows Tk integration')
class OverlayUITests(unittest.TestCase):
    setUp = fixtures.EditorUITests.setUp
    cleanup_ui = fixtures.EditorUITests.cleanup_ui
    pump_until = fixtures.EditorUITests.pump_until
    next_picture = fixtures.EditorUITests.next_picture

    def caption(self, text="Café's [OK]"):
        controls = self.window.overlay_tools
        controls.input.delete('1.0', 'end')
        controls.input.insert('1.0', text)
        controls.text_on.set(True)
        self.next_picture(controls.text_changed)

    def draw_mask(self):
        w = self.window
        self.next_picture(lambda: w.select_tool('PRIVACY'))
        left, top, width, height = w.video.bounds()
        x1, y1 = round(left+width*.25), round(top+height*.25)
        x2, y2 = round(left+width*.6), round(top+height*.6)
        before = w.video.photo
        w.video.event_generate('<Button-1>', x=x1, y=y1)
        w.video.event_generate('<B1-Motion>', x=x2, y=y2)
        w.video.event_generate('<ButtonRelease-1>')
        self.pump_until(lambda: w.video.photo is not before)
        self.assertIsNotNone(w.edits.privacy.mask)
        w.edits.validate(w.media)
        self.assertTrue(w.video.find_withtag('privacy'))

    def test_all_six_panels_fit_minimum_window_and_text_validation(self):
        w = self.window
        w.geometry('760x700')
        self.root.update()
        for name in ('TRIM', 'FORMAT', 'CROP', 'BRAND', 'TEXT', 'PRIVACY'):
            self.next_picture(lambda name=name: w.select_tool(name))
            self.assertGreater(w.video.winfo_height(), 120)
            self.assertGreaterEqual(w.timeline.winfo_height(), 65)
            def inspect(parent):
                for child in parent.winfo_children():
                    if child.winfo_ismapped():
                        self.assertLessEqual(child.winfo_y()+child.winfo_height(), parent.winfo_height()+1, f'{name}: {child}')
                        self.assertLessEqual(child.winfo_x()+child.winfo_width(), parent.winfo_width()+1, f'{name}: {child}')
                        inspect(child)
            inspect(w.panels[name])
        self.next_picture(lambda: w.select_tool('TEXT'))
        self.caption()
        self.assertTrue(w.edits.text.enabled)
        w.overlay_tools.input.delete('1.0', 'end')
        w.overlay_tools.text_changed()
        self.assertFalse(w.commit_entries())
        self.assertEqual(str(w.export_button.cget('state')), 'disabled')
        self.assertIn('Enter some text', w.note.cget('text'))
        self.assertIsNone(w.video.photo)
        self.caption('Restored')
        self.assertTrue(w.commit_entries())

    def test_draw_move_resize_mask_after_shifted_crop_and_format_changes(self):
        w = self.window
        self.next_picture(lambda: w.select_tool('FORMAT'))
        w.format_choice.set('9:16 Vertical')
        self.next_picture(w.format_changed)
        self.next_picture(lambda: w.select_tool('CROP'))
        w.crop_changed(w.edits.crop.moved(w.media, 100, 20))
        self.draw_mask()
        mask = w.edits.privacy.mask
        x1, y1, x2, y2 = w.video.screen_rect(mask)
        old = w.video.photo
        w.video.event_generate('<Button-1>', x=round((x1+x2)/2), y=round((y1+y2)/2))
        w.video.event_generate('<B1-Motion>', x=10000, y=10000)
        w.video.event_generate('<ButtonRelease-1>')
        self.pump_until(lambda: w.video.photo is not old)
        moved = w.edits.privacy.mask
        self.assertGreater(moved.x, mask.x)
        self.assertEqual(moved.right, w.video.viewport().right)
        self.assertEqual(moved.bottom, w.video.viewport().bottom)
        x1, y1, x2, y2 = w.video.screen_rect(moved)
        old = w.video.photo
        w.video.event_generate('<Button-1>', x=round(x1), y=round(y1))
        w.video.event_generate('<B1-Motion>', x=round(x1-15), y=round(y1-15))
        w.video.event_generate('<ButtonRelease-1>')
        self.pump_until(lambda: w.video.photo is not old)
        resized = w.edits.privacy.mask
        self.assertGreater(resized.width, moved.width)
        self.assertGreater(resized.height, moved.height)
        for preset in ('Original', '16:9 Landscape', '1:1 Square', '9:16 Vertical'):
            w.format_choice.set(preset)
            self.next_picture(w.format_changed)
            self.assertEqual(w.edits.privacy.mask, resized)
            self.assertEqual(w.video.visible_mask(), resized.intersect(w.video.viewport()))
        self.next_picture(lambda: w.overlay_tools.mask_changed(None))
        self.assertIsNone(w.edits.privacy.mask)
        self.assertFalse(w.video.find_withtag('privacy'))

    def test_combined_ui_export_and_preview_modes(self):
        w = self.window
        w.format_choice.set('9:16 Vertical')
        self.next_picture(w.format_changed)
        self.caption('Private clip')
        self.draw_mask()
        w.overlay_tools.privacy_mode.set('Pixelate')
        self.next_picture(w.overlay_tools.mode_changed)
        w.brand_on.set(True)
        self.next_picture(w.brand_changed)
        self.assertFalse(w.video.source_view)
        w.export()
        self.assertFalse(w.video.enabled)
        self.pump_until(lambda: w.last_export is not None)
        self.assertTrue(w.last_export.is_file())
        self.assertIn('EXPORTED', w.note.cget('text'))
        self.next_picture(lambda: w.select_tool('CROP'))
        self.assertTrue(w.video.source_view)
        self.assertFalse(w.video.find_withtag('privacy'))
        self.next_picture(lambda: w.select_tool('PRIVACY'))
        self.assertFalse(w.video.source_view)
        self.assertTrue(w.video.find_withtag('privacy'))

    def test_clipped_edge_and_window_resize_cannot_commit_invalid_mask(self):
        w = self.window
        w.format_choice.set('1:1 Square')
        self.next_picture(w.format_changed)
        mask = Rect(w.edits.crop.x-1, 100, 2, 30)
        self.next_picture(lambda: w.overlay_tools.mask_changed(mask))
        self.next_picture(lambda: w.select_tool('PRIVACY'))
        visible = w.video.visible_mask()
        self.assertEqual(visible.width, 1)
        x1, y1, _, _ = w.video.screen_rect(visible)
        w.video.event_generate('<Button-1>', x=round(x1), y=round(y1))
        w.video.event_generate('<ButtonRelease-1>')
        self.root.update()
        self.assertEqual(w.edits.privacy.mask, mask)
        self.next_picture(lambda: w.video.nudge(2, 0))
        w.edits.validate(w.media)
        self.next_picture(lambda: w.overlay_tools.mask_changed(None))
        self.draw_mask()
        mask = w.edits.privacy.mask
        x1, y1, x2, y2 = w.video.screen_rect(mask)
        w.video.event_generate('<Button-1>', x=round((x1+x2)/2), y=round((y1+y2)/2))
        self.assertIsNotNone(w.video.gesture)
        w.geometry('800x720')
        self.root.update()
        self.assertIsNone(w.video.gesture)
        w.video.event_generate('<ButtonRelease-1>')
        self.assertEqual(w.edits.privacy.mask, mask)

    def test_close_during_combined_export(self):
        w = self.window
        self.caption('Private clip')
        self.draw_mask()
        children = []
        def slow_popen(command, **kwargs):
            command.insert(command.index('-i'), '-re')
            child = subprocess.Popen(command, **kwargs)
            children.append(child)
            return child
        w.exporter._popen = slow_popen
        w.export()
        self.pump_until(lambda: bool(children))
        w.close()
        self.pump_until(lambda: w.closed)
        self.assertIsNotNone(children[0].poll())
        self.assertEqual(list(self.folder.iterdir()), [self.source])
