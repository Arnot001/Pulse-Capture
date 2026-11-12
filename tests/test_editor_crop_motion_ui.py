"""Opt-in Windows/Tk check for the YouTube Shorts keyframe workflow."""
import os
import unittest
from tests import test_editor_ui as fixtures
from editor.transforms import SHORTS_FORMAT


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
