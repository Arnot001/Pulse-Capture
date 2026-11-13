"""Opt-in Windows/Tk check for the YouTube Shorts keyframe workflow."""
import os
import unittest
from tests import test_editor_ui as fixtures
from editor.transforms import SHORTS_FORMAT
from ui import theme as t


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1',
                     'Opt-in Windows Tk integration')
class CropMotionUITests(unittest.TestCase):
    setUp = fixtures.EditorUITests.setUp
    cleanup_ui = fixtures.EditorUITests.cleanup_ui
    pump_until = fixtures.EditorUITests.pump_until
    next_picture = fixtures.EditorUITests.next_picture

    def test_add_move_scrub_render_and_clear(self):
        w = self.window
        w.format_choice.set(SHORTS_FORMAT)
        self.next_picture(w.format_changed)
        self.next_picture(lambda: w.select_tool('CROP'))
        self.assertTrue(all(str(button['state']) == 'normal'
                            for button in w.crop_key_buttons))
        w.add_crop_keyframe()
        self.assertEqual(len(w.edits.crop_motion.keyframes), 1)
        first = w.edits.crop
        self.next_picture(lambda: w.seek(1))
        self.assertEqual(w.video.crop, first)
        second = first.moved(w.media, first.x + 100, first.y)
        w.crop_changed(second)
        self.assertEqual(len(w.edits.crop_motion.keyframes), 2)
        self.assertEqual(w.video.crop, second)
        self.assertTrue(w.timeline.find_withtag('crop-keyframe'))
        self.next_picture(lambda: w.seek(.5))
        self.assertGreater(w.video.crop.x, first.x)
        self.assertLess(w.video.crop.x, second.x)
        self.next_picture(lambda: w.select_tool('FORMAT'))
        self.assertFalse(w.video.source_view)
        self.next_picture(lambda: w.select_tool('CROP'))
        self.next_picture(lambda: w.seek(1))
        w.delete_crop_keyframe()
        self.assertEqual(len(w.edits.crop_motion.keyframes), 1)
        w.clear_crop_keyframes()
        self.assertEqual(w.edits.crop_motion.keyframes, ())
        self.assertEqual(w.edits.crop, w.video.crop)

    def test_corner_handle_resizes_and_keeps_saved_crop_keys(self):
        w = self.window
        w.format_choice.set(SHORTS_FORMAT)
        self.next_picture(w.format_changed)
        self.next_picture(lambda: w.select_tool('CROP'))
        w.add_crop_keyframe()
        first = w.edits.crop
        self.next_picture(lambda: w.seek(1))
        second = first.moved(w.media, first.x + 30, first.y)
        w.crop_changed(second)
        self.assertEqual(len(w.edits.crop_motion.keyframes), 2)
        x1, y1, _, _ = w.video.crop_bounds()
        w.video.event_generate('<Button-1>', x=round(x1), y=round(y1))
        self.assertEqual(w.video.drag[0], 'resize')
        w.video.event_generate('<B1-Motion>', x=round(x1+35), y=round(y1+35))
        w.video.event_generate('<ButtonRelease-1>')
        self.root.update()
        self.assertLess(w.edits.crop.width, first.width)
        self.assertEqual(len(w.edits.crop_motion.keyframes), 2)
        self.assertEqual(w.video.crop.width, w.edits.crop.width)
        self.assertEqual(w.edits.crop.width*16, w.edits.crop.height*9)
        self.next_picture(lambda: w.select_tool('FORMAT'))
        self.assertFalse(w.video.source_view)
        self.assertFalse(self.errors)

    def test_formats_display_one_vertical_and_one_horizontal_option(self):
        w = self.window
        for panel_name in ('FORMAT', 'CROP'):
            panel = w.panels[panel_name]
            segments = next(child for child in panel.winfo_children()
                            if isinstance(child, t.Segments))
            self.assertEqual(len(segments.buttons), 4)
            values = [value for value, button in segments.buttons]
            labels = [str(button.cget('text')) for value, button in segments.buttons]
            self.assertEqual(values, ['Original', '16:9 Landscape',
                                      SHORTS_FORMAT, '1:1 Square'])
            self.assertNotIn('9:16 Vertical', values)
            self.assertIn('16:9\nHorizontal', labels)

    def test_switching_format_clears_keyframes_and_disables_controls(self):
        w = self.window
        w.format_choice.set(SHORTS_FORMAT)
        self.next_picture(w.format_changed)
        w.add_crop_keyframe()
        self.assertEqual(len(w.edits.crop_motion.keyframes), 1)
        w.format_choice.set('1:1 Square')
        self.next_picture(w.format_changed)
        self.assertEqual(w.edits.crop_motion.keyframes, ())
        self.assertTrue(all(str(button['state']) == 'disabled'
                            for button in w.crop_key_buttons))


if __name__ == '__main__':
    unittest.main()
