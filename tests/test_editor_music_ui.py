"""Windows Tk checks for the Quick Edit Music panel."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from editor.music import IMPORT_LABEL, TRACKS
from tests import test_editor_ui as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1', 'Opt-in Windows Tk integration')
class MusicUITests(unittest.TestCase):
    setUp = fixtures.EditorUITests.setUp
    cleanup_ui = fixtures.EditorUITests.cleanup_ui
    pump_until = fixtures.EditorUITests.pump_until
    next_picture = fixtures.EditorUITests.next_picture

    def test_music_panel_enable_track_volume_loop_and_fades(self):
        w = self.window
        controls = w.music_tools
        self.next_picture(lambda: w.select_tool('MUSIC'))
        self.assertIn('MUSIC', w.panels)
        self.assertFalse(w.edits.music.enabled)

        controls.music_on.set(True)
        controls.track_choice.set('Pulse // Drive')
        controls.music_volume.set('15%')
        controls.original_volume.set('75%')
        controls.loop.set(False)
        controls.fade_in.set(False)
        controls.fade_out.set(True)
        controls.changed()
        self.root.update()

        music = w.edits.music
        self.assertTrue(music.enabled)
        self.assertEqual(music.track, 'Pulse // Drive')
        self.assertEqual(music.music_volume, .15)
        self.assertEqual(music.original_volume, .75)
        self.assertFalse(music.loop)
        self.assertFalse(music.fade_in)
        self.assertTrue(music.fade_out)
        self.assertIn('124 BPM', controls.hint.cget('text'))
        self.assertIn('Music + source audio', w.preview_note.cget('text'))

        controls.music_on.set(False)
        controls.changed()
        self.root.update()
        self.assertFalse(w.edits.music.enabled)
        self.assertIn('Audio kept on export', w.preview_note.cget('text'))

    def test_import_mp3_wav_and_switch_back_to_pulse_track(self):
        w = self.window
        controls = w.music_tools
        imported = self.folder / 'my soundtrack.wav'
        imported.touch()
        self.next_picture(lambda: w.select_tool('MUSIC'))

        with patch('editor.music_tools.filedialog.askopenfilename', return_value=str(imported)):
            controls.import_audio()
        self.root.update()

        self.assertTrue(w.edits.music.enabled)
        self.assertEqual(w.edits.music.track, IMPORT_LABEL)
        self.assertEqual(w.edits.music.imported, imported)
        self.assertIn(IMPORT_LABEL, controls.track_combo.cget('values'))
        self.assertIn(imported.name, controls.hint.cget('text'))

        controls.track_choice.set('Pulse // Focus')
        controls.changed()
        self.root.update()
        self.assertEqual(w.edits.music.track, 'Pulse // Focus')
        self.assertEqual(w.edits.music.imported, imported)
        self.assertIn(IMPORT_LABEL, controls.track_combo.cget('values'))

    def test_minimum_layout_and_busy_states(self):
        w = self.window
        controls = w.music_tools
        self.next_picture(lambda: w.select_tool('MUSIC'))
        controls.music_on.set(True)
        controls.changed()
        self.root.update()

        w.geometry('760x700')
        self.root.update()
        panel = w.panels['MUSIC']
        self.assertGreater(w.video.winfo_height(), 110)
        self.assertGreaterEqual(w.timeline.winfo_height(), 65)

        def inspect(parent):
            for child in parent.winfo_children():
                if child.winfo_ismapped():
                    self.assertLessEqual(
                        child.winfo_y() + child.winfo_height(),
                        parent.winfo_height() + 1,
                        f'MUSIC: {child} extends below {parent}',
                    )
                    self.assertLessEqual(
                        child.winfo_x() + child.winfo_width(),
                        parent.winfo_width() + 1,
                        f'MUSIC: {child} extends beyond {parent}',
                    )
                    inspect(child)
        inspect(panel)

        w.set_busy(True)
        for widget in (
            controls.track_combo, controls.import_button,
            controls.music_volume_combo, controls.original_volume_combo,
            *controls.option_checks,
        ):
            self.assertEqual(str(widget.cget('state')), 'disabled')
        w.set_busy(False)
        self.assertEqual(str(controls.track_combo.cget('state')), 'readonly')
        for widget in controls.option_checks:
            self.assertEqual(str(widget.cget('state')), 'normal')

    def test_all_builtin_tracks_are_selectable_without_changing_other_edits(self):
        w = self.window
        controls = w.music_tools
        original_privacy = w.edits.privacy
        original_crop = w.edits.crop
        self.next_picture(lambda: w.select_tool('MUSIC'))
        controls.music_on.set(True)
        for name in TRACKS:
            controls.track_choice.set(name)
            controls.changed()
            self.root.update()
            self.assertEqual(w.edits.music.track, name)
            self.assertEqual(w.edits.privacy, original_privacy)
            self.assertEqual(w.edits.crop, original_crop)


if __name__ == '__main__':
    unittest.main()
