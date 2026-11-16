"""Import → render → captions → export in Tk; optional real Windows recording."""
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import Backend, run
from editor.editor_window import EditorWindow
from editor.pulse_plan import starter_plan, source_identity
from editor.transforms import FULL_FRAME_FORMAT
from editor.privacy import Rect
from ui import theme


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1', 'Opt-in Windows Tk integration')
class PulsePlanUITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.backend = Backend(shutil.which('ffmpeg'), shutil.which('ffprobe'), True)
        self.source = self.folder/'recording.mp4'
        if os.environ.get('PULSE_REAL_RECORDING'):
            shutil.copyfile(os.environ['PULSE_REAL_RECORDING'], self.source)
        else:
            result = run([self.backend.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                          'testsrc2=s=640x360:r=30', '-t', '6', '-c:v', 'libx264', str(self.source)], 30)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.root = tk.Tk()
        self.root.withdraw()
        theme.install(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.window = EditorWindow(self.root, self.source, self.backend)
        self.addCleanup(self.cleanup)
        self.pump(lambda: self.window.media and self.window.video.photo)

    def pump(self, condition, timeout=90):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            self.root.update()
            self.assertFalse(self.errors, self.errors)
            if condition():
                return
            time.sleep(.02)
        self.fail(f'Tk timeout; {self.window.note.cget("text")}; {self.errors}')

    def cleanup(self):
        self.window.close()
        self.pump(lambda: self.window.closed)
        if self.window.preview:
            self.window.preview._thread.join(15)
        self.root.destroy()

    def test_import_preview_edit_export_and_recipe_revision(self):
        media = self.window.media
        plan = starter_plan(media, source_identity(media, threading.Event()))
        plan['timeline'][1].update(start=2, end=3, commentary='Script for later recording.')
        plan['captions'] = [dict(start=1, end=2, text='Editable caption', zone='bottom', basis='joke')]
        path = self.folder/'plan.json'
        path.write_text(json.dumps(plan), encoding='utf-8')
        self.window.open_auto_edit()
        auto = self.window.auto_dialog
        with patch('editor.pulse_tools.filedialog.askopenfilename', return_value=str(path)):
            auto.import_button.invoke()
        dialog = next(iter(self.window.auto_children))
        self.assertEqual(len(dialog.timeline.get_children()), 4)
        with patch('editor.pulse_tools.default_cache', return_value=self.folder/'cache'):
            dialog.actions[-1].invoke()
            self.pump(lambda: not dialog.busy)
        candidates = [child for child in self.window.auto_children if isinstance(child, EditorWindow)]
        self.assertEqual(len(candidates), 1, dialog.status.cget('text'))
        child = candidates[0]
        self.pump(lambda: child.media and child.video.photo)
        self.assertEqual((child.media.width, child.media.height), (1080, 1920))
        self.assertEqual(child.edits.text.captions[0].text, 'Editable caption')
        from editor.caption_tools import CaptionDialog
        child.overlay_tools.caption_button.invoke()
        captions = next(widget for widget in child.winfo_children() if isinstance(widget, CaptionDialog))
        captions.rows.selection_set(0)
        captions.select()
        captions.input.delete('1.0', 'end')
        captions.input.insert('1.0', 'Revised punchline')
        captions.save(True)
        self.assertEqual(child.edits.text.captions[0].text, 'Revised punchline')
        captions.destroy()
        # The real caption tools are opened, playback is exercised, and the
        # assembled clock starts at zero rather than a reused source timestamp.
        child.play_preview()
        self.pump(lambda: child.position > .1)
        child.pause_preview()
        self.assertFalse(child.playing)
        child.stop_preview()
        child.export()
        self.pump(lambda: child.last_export is not None or
                  (not child.exporter.busy and str(child.export_button.cget('state')) == 'normal'))
        self.assertIsNotNone(child.last_export, child.note.cget('text'))
        self.assertTrue(child.last_export.is_file())
        child.open_pulse_plan()
        recipe = next(iter(child.auto_children))
        self.assertEqual(recipe.media.path, media.path)
        self.assertEqual(recipe.get_plan(), plan)
        recipe.close()
        # Reject an unsupported effect without spawning an assembly job.
        dialog.editor.insert('end', 'not json')
        self.assertIsNone(dialog.validate())
        self.assertFalse(dialog.busy)

    def test_full_frame_privacy_and_focus_map_to_picture_not_panels(self):
        w = self.window
        w.select_tool('FORMAT')
        w.format_choice.set(FULL_FRAME_FORMAT)
        old = w.video.photo
        w.format_changed()
        self.pump(lambda: w.video.photo is not old)
        x, y, width, height = w.video.content_bounds()
        mx, my = w.video.source_point(x+width/2, y+height/2)
        self.assertAlmostEqual(mx, w.media.width/2, delta=1)
        self.assertAlmostEqual(my, w.media.height/2, delta=1)
        rect = Rect(10, 20, 100, 80)
        left, top, right, bottom = w.video.screen_rect(rect)
        self.assertAlmostEqual(w.video.source_point(left, top)[0], rect.x, delta=1)
        self.assertAlmostEqual(w.video.source_point(right, bottom)[1], rect.bottom, delta=1)
        self.assertGreater(y, w.video.bounds()[1])


if __name__ == '__main__':
    unittest.main()
