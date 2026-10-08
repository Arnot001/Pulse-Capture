"""Opt-in Tk integration checks on Windows: PULSE_RUN_UI_TESTS=1."""
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
import tkinter as tk
import unittest
from capture.ffmpeg_backend import Backend, run
from capture.window_picker import enable_dpi_awareness
from editor.editor_window import EditorWindow
from editor.models import TrimRange
from ui import theme


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1', 'Opt-in Windows Tk integration')
class EditorUITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.ffmpeg, self.probe = shutil.which('ffmpeg'), shutil.which('ffprobe')
        self.assertTrue(self.ffmpeg and self.probe)
        self.source = self.folder / 'ui sample.mp4'
        result = run([self.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                      'testsrc2=size=640x480:rate=30', '-t', '4', '-c:v', 'libx264', str(self.source)], 30)
        self.assertEqual(result.returncode, 0, result.stderr)
        enable_dpi_awareness()
        self.root = tk.Tk()
        self.root.withdraw()
        theme.install(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.window = EditorWindow(self.root, self.source, Backend(self.ffmpeg, self.probe, True))
        self.addCleanup(self.cleanup_ui)
        self.pump_until(lambda: self.window.media and self.window.video.photo)

    def cleanup_ui(self):
        if not self.window.closed:
            self.window.close()
            self.pump_until(lambda: self.window.closed)
        if self.window.preview:
            self.window.preview._thread.join(15)
        self.root.destroy()

    def pump_until(self, condition, timeout=15):
        deadline = time.monotonic()+timeout
        while time.monotonic() < deadline:
            self.root.update()
            if condition():
                self.assertFalse(self.errors, self.errors)
                return
            time.sleep(.02)
        self.fail(f'Tk condition timed out: {self.window.note.cget("text")} / {self.errors}')

    def next_picture(self, action):
        old = self.window.video.photo
        action()
        self.pump_until(lambda: self.window.video.photo is not old)

    def test_tools_crop_drag_trim_brand_export_and_small_window(self):
        w = self.window
        self.assertFalse(w.edits.branding.enabled)
        self.next_picture(lambda: w.select_tool('FORMAT'))
        w.format_choice.set('9:16 Vertical')
        self.next_picture(w.format_changed)
        self.assertLess(w.video.photo.width(), w.video.photo.height())
        self.next_picture(lambda: w.select_tool('CROP'))
        self.assertTrue(w.video.source_view)
        self.assertTrue(w.video.find_withtag('crop'))
        crop_before = w.edits.crop
        x1, y1, x2, y2 = w.video.crop_bounds()
        w.video.event_generate('<Button-1>', x=round((x1+x2)/2), y=round((y1+y2)/2))
        w.video.event_generate('<B1-Motion>', x=10000, y=10000)
        w.video.event_generate('<ButtonRelease-1>')
        self.root.update()
        self.assertNotEqual(w.edits.crop.x, crop_before.x)
        w.edits.validate(w.media)
        crop_after = w.edits.crop
        w.update_trim(TrimRange(.5, 2.5))
        self.assertEqual(w.edits.crop, crop_after)
        self.next_picture(lambda: w.select_tool('BRAND'))
        self.assertFalse(w.video.find_withtag('crop'))
        w.brand_on.set(True)
        w.brand_corner.set('Top left')
        w.brand_size.set('Large')
        self.next_picture(w.brand_changed)
        self.assertTrue(w.edits.branding.enabled)
        w.geometry('760x700')
        self.root.update()
        for name in ('TRIM', 'FORMAT', 'CROP', 'BRAND'):
            self.next_picture(lambda name=name: w.select_tool(name))
            panel = w.panels[name]
            self.assertGreater(w.video.winfo_height(), 120)
            self.assertGreaterEqual(w.timeline.winfo_height(), 65)
            self.assertGreater(w.export_button.winfo_height(), 30)
            # Every visible tool control fits its panel, including the last row.
            def check_children(parent):
                for child in parent.winfo_children():
                    if child.winfo_ismapped():
                        self.assertLessEqual(child.winfo_y()+child.winfo_height(), parent.winfo_height()+1,
                                             f'{name}: {child} extends below {parent}')
                        self.assertLessEqual(child.winfo_x()+child.winfo_width(), parent.winfo_width()+1,
                                             f'{name}: {child} extends beyond {parent}')
                        check_children(child)
            check_children(panel)
        w.export()
        self.assertFalse(w.video.enabled)
        self.pump_until(lambda: w.last_export is not None)
        self.assertTrue(w.last_export.is_file())
        self.assertIn('EXPORTED', w.note.cget('text'))
        self.assertTrue(w.video.enabled)
        w.format_choice.set('Original')
        self.next_picture(w.format_changed)
        self.assertIsNone(w.edits.crop)
        self.assertEqual(w.trim, TrimRange(.5, 2.5))
        self.assertFalse(self.errors)

    def test_close_cancels_live_export(self):
        w = self.window
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
