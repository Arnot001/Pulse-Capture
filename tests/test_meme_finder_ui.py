"""Windows-only, opt-in native in-app sound discovery workflow (offline fixtures)."""
import gc
import os
from pathlib import Path
from unittest.mock import patch
import unittest

from capture.ffmpeg_backend import run
from editor.reaction_tools import ReactionDialog
from editor.meme_finder import MemeFinder
from tests import test_pulse_plan_ui as fixture


@unittest.skipUnless(os.environ.get("PULSE_RUN_UI_TESTS") == "1",
                     "Opt-in Windows Tk integration")
class MemeFinderUITests(unittest.TestCase):
    pump = fixture.PulsePlanUITests.pump

    def setUp(self):
        gc.collect()
        fixture.PulsePlanUITests.setUp(self)
        self.library_patch = patch.dict(
            os.environ, PULSE_REACTION_LIBRARY=str(self.folder / "meme-library"))
        self.library_patch.start()
        self.addCleanup(self.library_patch.stop)

    def test_search_preview_and_import_without_external_browser(self):
        item = dict(id="fixture.wav", name="Our own WTF shout",
                    creator="Pulse Test", license="CC0",
                    license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                    source="https://freesound.org/people/test/sounds/123/",
                    audio="https://cdn.freesound.org/previews/test.wav",
                    suffix=".wav", attribution="Pulse Test - CC0")
        source = self.folder / "fixture.wav"
        result = run([self.window.backend.ffmpeg, "-v", "error", "-f", "lavfi",
                      "-i", "sine=frequency=800:duration=0.5", str(source)], 15)
        self.assertEqual(result.returncode, 0, result.stderr)

        def fake_fetch(_item, path, cancelled=None):
            Path(path).write_bytes(source.read_bytes())
            return Path(path)

        dialog = ReactionDialog(self.window, "sfx")
        self.addCleanup(dialog.close)
        self.finder = None
        with patch("editor.meme_finder.search_openverse", return_value=[item]) as search, \
             patch("editor.meme_finder.fetch_audio", side_effect=fake_fetch) as fetch, \
             patch("editor.meme_finder.messagebox.askyesno", return_value=True) as confirm, \
             patch("editor.meme_finder.webbrowser.open") as browser:
            self.finder = MemeFinder(dialog)
            self.addCleanup(self.finder.close)
            self.pump(lambda: not self.finder.busy and self.finder.listbox.size() == 1)
            search.assert_called_once()
            self.finder.listbox.selection_set(0)
            self.finder.selected_changed()
            self.assertIn("CC0", self.finder.details.cget("text"))

            self.finder.preview()
            self.pump(lambda: not self.finder.busy)
            fetch.assert_called_once()
            self.pump(lambda: "Playing preview" in self.finder.note.cget("text"))
            self.finder.stop()

            self.finder.import_selected()
            self.pump(lambda: not self.finder.busy)
            confirm.assert_called_once()
            self.assertIn("Imported into SOUND FX", self.finder.note.cget("text"))
            browser.assert_not_called()

            key = dialog.selected()
            meta = dialog.library.metadata(key)
            self.assertEqual(meta["rights_status"], "Unverified")
            self.assertEqual(meta["name"], "Our own WTF shout")
            self.assertEqual(meta["artist"], "Pulse Test")
            self.assertEqual(meta["attribution"], "Pulse Test - CC0")
            self.assertIn("Openverse index:", meta["licence"])

            dialog.insert()
            self.assertEqual(self.window.edits.sounds[0].asset_id, key)



if __name__ == "__main__":
    unittest.main()
