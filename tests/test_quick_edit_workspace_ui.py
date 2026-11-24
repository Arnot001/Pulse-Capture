"""Windows Tk smoke checks for preview-first Quick Edit layout.

Mocks only the decoding workers; real Tk layout, callbacks and tool panels
are exercised. No FFmpeg install, capture device or paid API is required.
"""
from contextlib import ExitStack
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import os
import time
import tkinter as tk
import unittest

from editor.editor_window import EditorWindow
from editor.models import MediaInfo
from ui import theme


class NoDecodePreview:
    def __init__(self, *_args, **_kwargs):
        self.frames = Queue()
        self.requested = []
    def request(self, *args):
        self.requested.append(args)
    def close(self):
        pass


class NoDecodePlayback:
    def __init__(self, *_args, **_kwargs):
        self.error = None
    def stop(self):
        pass
    def close(self):
        pass


class NoDeviceAudio:
    def __init__(self, *_args, **_kwargs):
        self.errors = Queue()
    def stop(self):
        pass
    def close(self):
        pass


@unittest.skipUnless(os.name == 'nt' and os.environ.get('PULSE_RUN_UI_TESTS') == '1',
                     'Opt-in Windows Tk workspace checks')
class QuickEditWorkspaceUITests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        theme.install(self.root)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        path = Path(self.temp.name) / 'sample.mp4'
        path.write_bytes(b'recording-preserved')
        self.original = path
        media = MediaInfo(path, 30., 640, 360, 30, False)
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch('editor.editor_window.probe_media', return_value=media))
        self.patches.enter_context(patch('editor.editor_window.Preview', NoDecodePreview))
        self.patches.enter_context(patch('editor.editor_window.PlaybackPreview', NoDecodePlayback))
        self.patches.enter_context(patch('editor.editor_window.AudioPlayback', NoDeviceAudio))
        backend = SimpleNamespace(ffmpeg='unused', ffprobe='unused')
        self.window = EditorWindow(self.root, path, backend)
        self.addCleanup(self.close_window)
        self.pump_until(lambda: self.window.media is not None)

    def pump_until(self, predicate, seconds=3):
        limit = time.monotonic() + seconds
        while time.monotonic() < limit:
            self.root.update()
            if predicate():
                self.assertEqual(self.errors, [])
                return
            time.sleep(.01)
        self.fail('Workspace did not initialise or update')

    def close_window(self):
        if not self.window.closed:
            self.window.close()
            self.pump_until(lambda: self.window.closed)

    def test_default_preview_is_tall_and_inspector_is_hidden(self):
        w = self.window
        self.assertFalse(w.inspector_visible)
        self.assertFalse(w.inspector.winfo_ismapped())
        self.assertGreater(w.video.winfo_height(), 170)
        self.assertGreater(w.video.winfo_height(), w.export_button.winfo_height() * 3)
        self.assertTrue(w.timeline.winfo_ismapped())
        self.assertEqual(w.tool.get(), 'TRIM')
        self.assertEqual(w.add_menu.cget('state'), 'normal')
        self.assertEqual(w.workspace_menu.cget('state'), 'normal')

    def test_each_tool_gets_its_own_panel_and_can_be_closed(self):
        w = self.window
        for name in ('TRIM', 'FORMAT', 'CROP', 'BRAND', 'MUSIC', 'PRIVACY'):
            w.toggle_tool(name)
            self.root.update()
            self.assertTrue(w.inspector_visible, name)
            self.assertEqual(w.tool.get(), name)
            self.assertTrue(w.panels[name].winfo_ismapped(), name)
            self.assertIn(w.tool_titles[name].upper(), w.inspector_title.cget('text'))
            w.toggle_tool(name)
            self.root.update()
            self.assertFalse(w.inspector_visible, name)
            self.assertFalse(w.inspector.winfo_ismapped(), name)
            self.assertFalse(w.video.active)
        self.assertEqual(self.errors, [])

    def test_small_window_video_still_visible_and_timeline_can_resize(self):
        w = self.window
        w.geometry('840x700')
        self.root.update()
        self.assertGreater(w.video.winfo_height(), 140)
        self.assertGreaterEqual(w.timeline.winfo_height(), 65)
        before = w.video.winfo_height()
        # Tk paned split adjusts picture and track heights independently.
        _x, y = w.preview_split.sash_coord(0)
        w.preview_split.sash_place(0, 0, y + 24)
        self.root.update()
        self.assertNotEqual(w.video.winfo_height(), before)
        self.assertGreater(w.video.winfo_height(), 140)
        w.select_tool('TEXT')
        self.root.update()
        self.assertTrue(w.panels['TEXT'].winfo_ismapped())
        self.assertGreater(w.video.winfo_height(), 120)
        self.assertGreaterEqual(w.timeline.winfo_height(), 65)

    def test_dropdowns_keep_media_voice_and_edit_modes(self):
        w = self.window
        titles = [w.workspace_actions.entrycget(i, 'label')
                  for i in range(w.workspace_actions.index('end') + 1)
                  if w.workspace_actions.type(i) == 'command']
        self.assertEqual(titles, ['Quick Edit', 'Auto Edit', 'AI Voiceover', 'Roast Studio'])
        additions = [w.add_menu.cget('menu')]
        self.assertEqual(len(additions), 1)
        w.select_tool('CROP')
        self.assertTrue(w.video.active)
        w.hide_inspector()
        self.assertFalse(w.video.active)
        self.assertEqual(self.original.read_bytes(), b'recording-preserved')

    def test_export_busy_disables_toolbar_and_recovers(self):
        w = self.window
        w.select_tool('FORMAT')
        w.set_busy(True)
        self.assertEqual(str(w.add_menu.cget('state')), 'disabled')
        self.assertEqual(str(w.workspace_menu.cget('state')), 'disabled')
        self.assertEqual(str(w.tool_buttons['FORMAT'].cget('state')), 'disabled')
        w.set_busy(False)
        self.assertEqual(str(w.add_menu.cget('state')), 'normal')
        self.assertEqual(str(w.tool_buttons['FORMAT'].cget('state')), 'normal')


if __name__ == '__main__':
    unittest.main()
