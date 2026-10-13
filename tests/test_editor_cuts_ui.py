"""Opt-in Tk checks for the v0.6 non-destructive CUT workflow."""
import hashlib
import os
import time
import unittest

from editor.cuts import CutPlan, CutRange
from editor.media import probe_media
from editor.models import TrimRange
from tests import test_editor_ui as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1', 'Opt-in Windows Tk integration')
class CutUITests(unittest.TestCase):
    setUp = fixtures.EditorUITests.setUp
    cleanup_ui = fixtures.EditorUITests.cleanup_ui
    pump_until = fixtures.EditorUITests.pump_until
    next_picture = fixtures.EditorUITests.next_picture

    def add_cut(self, start, end):
        w = self.window
        controls = w.cut_tools
        self.next_picture(lambda: w.seek(start))
        controls.start_button.invoke()
        self.next_picture(lambda: w.seek(end))
        controls.end_button.invoke()
        self.next_picture(controls.remove_button.invoke)

    def test_cut_panel_add_restore_undo_timeline_and_minimum_layout(self):
        w = self.window
        self.assertIn('CUT', w.panels)
        self.assertEqual(len(w.panels), 10)
        self.next_picture(lambda: w.select_tool('CUT'))
        controls = w.cut_tools
        self.assertEqual(str(controls.remove_button.cget('state')), 'disabled')

        self.add_cut(.75, 1.25)
        self.assertEqual(w.cuts.ranges, (CutRange(.75, 1.25),))
        self.assertEqual(controls.listbox.size(), 1)
        self.assertTrue(w.timeline.find_withtag('cut'))
        self.assertIn('After cuts', w.selection_label.cget('text'))
        self.assertAlmostEqual(w.position, 1.25, delta=.04)

        self.add_cut(2.0, 2.5)
        self.assertEqual(len(w.cuts.ranges), 2)
        controls.listbox.selection_clear(0, 'end')
        controls.listbox.selection_set(0)
        controls.selection_changed()
        self.next_picture(controls.restore_button.invoke)
        self.assertEqual(w.cuts.ranges, (CutRange(2.0, 2.5),))

        self.next_picture(controls.undo_button.invoke)
        self.assertEqual(w.cuts.ranges, ())
        self.assertEqual(controls.listbox.size(), 0)
        self.assertFalse(w.timeline.find_withtag('cut'))

        w.geometry('760x700')
        self.next_picture(lambda: w.select_tool('CUT'))
        panel = w.panels['CUT']
        self.root.update()
        self.assertGreater(w.video.winfo_height(), 110)
        self.assertGreaterEqual(w.timeline.winfo_height(), 65)

        def inspect(parent):
            for child in parent.winfo_children():
                if child.winfo_ismapped():
                    self.assertLessEqual(
                        child.winfo_y()+child.winfo_height(), parent.winfo_height()+1,
                        f'CUT: {child} extends below {parent}',
                    )
                    self.assertLessEqual(
                        child.winfo_x()+child.winfo_width(), parent.winfo_width()+1,
                        f'CUT: {child} extends beyond {parent}',
                    )
                    inspect(child)
        inspect(panel)

    def test_playback_skips_removed_section_and_stop_uses_first_kept_frame(self):
        w = self.window
        w.cuts = CutPlan((CutRange(1.0, 2.0),))
        w.cut_tools.refresh()
        w.update_selection_label()
        w.update_timeline()
        self.next_picture(lambda: w.seek(.9))

        positions = []
        original_update = w.update_timeline
        def tracked_update():
            positions.append(w.position)
            original_update()
        w.update_timeline = tracked_update
        try:
            w.play_preview()
            self.pump_until(lambda: w.position > 2.05, timeout=8)
            w.pause_preview()
        finally:
            w.update_timeline = original_update

        self.assertFalse(any(1.01 < position < 1.99 for position in positions), positions)
        self.assertGreater(w.position, 2.0)

        w.update_trim(TrimRange(.5, 2.5))
        w.cuts = CutPlan((CutRange(.5, 1.0),))
        w.cut_tools.refresh()
        w.seek(1.5)
        w.stop_preview()
        self.assertAlmostEqual(w.position, 1.0, places=2)

    def test_cut_export_has_shorter_duration_and_preserves_source(self):
        w = self.window
        digest = hashlib.sha256(w.path.read_bytes()).digest()
        w.cuts = CutPlan((CutRange(1.0, 2.0),))
        w.cut_tools.refresh()
        w.update_selection_label()
        w.update_timeline()

        w.export()
        self.pump_until(lambda: w.last_export is not None, timeout=30)
        exported = probe_media(self.probe, w.last_export)
        self.assertAlmostEqual(exported.duration, 3.0, delta=.15)
        self.assertEqual(hashlib.sha256(w.path.read_bytes()).digest(), digest)
        self.assertIn('EXPORTED', w.note.cget('text'))

    def test_trim_cannot_select_only_a_removed_section(self):
        w = self.window
        w.cuts = CutPlan((CutRange(1.0, 2.0),))
        w.cut_tools.refresh()
        w.start_text.set('1.100')
        w.end_text.set('1.900')
        self.assertFalse(w.commit_entries())
        self.assertIn('remove the entire selected video', w.note.cget('text').lower())


if __name__ == '__main__':
    unittest.main()
