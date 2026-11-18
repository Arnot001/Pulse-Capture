"""Opt-in Windows integration for dedicated Roast Studio controls and safety prompt."""
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from editor.pulse_plan import source_identity
from editor.roast_studio import RoastStudioDialog
from tests import test_pulse_plan_ui as fixture


@unittest.skipUnless(os.environ.get("PULSE_RUN_UI_TESTS") == "1",
                     "Opt-in Windows Tk integration")
class RoastStudioUITests(unittest.TestCase):
    setUp = fixture.PulsePlanUITests.setUp
    cleanup = fixture.PulsePlanUITests.cleanup
    pump = fixture.PulsePlanUITests.pump

    def test_json_load_source_mismatch_offset_and_band_render_handoff(self):
        source = self.window.media
        template = dict(
            format="pulse-edit-plan", version=2, title="Roast Studio fixture",
            style="Comedy / Roast",
            source=dict(name="different-long.mp4", duration=20.0,
                        width=source.width, height=source.height,
                        fps=source.fps, sha256="a"*64),
            output=dict(width=1080, height=1920, fps=30,
                        framing="full_frame", background="dark"),
            timeline=[
                dict(kind="shot", start=2.0, end=3.0, role="setup"),
                dict(kind="freeze", source_time=2.5, duration=1.0, role="punchline"),
            ],
            captions=[dict(start=0.0, end=1.0, text="IN A LIFT.",
                           zone="top", basis="joke")],
            caption_theme="Comedy Bold", freeze_duration=1.0,
            sfx=[], overlays=[], notes="Mock scene",
        )
        path = self.folder / "roast.json"
        path.write_text(json.dumps(template), encoding="utf-8")

        self.window.open_roast_studio()
        studio = next(child for child in self.window.auto_children
                      if isinstance(child, RoastStudioDialog))
        with patch("editor.roast_studio.filedialog.askopenfilename", return_value=str(path)):
            studio.load()
        self.assertIsNotNone(studio.plan)
        studio.offset.set("-2")

        calls = []
        class FakePlanEditor:
            def render(self):
                calls.append("render")

        def open_editor(window, plan, media):
            calls.append((window, plan, media))
            return FakePlanEditor()

        with patch("editor.roast_studio.messagebox.askyesno", return_value=True) as confirm, \
             patch("editor.pulse_tools.open_plan_dialog", side_effect=open_editor):
            studio.build()
            self.pump(lambda: studio.closed)
        confirm.assert_called_once()
        self.assertEqual(calls[-1], "render")
        bound = calls[0][1]
        self.assertEqual(bound["source"], source_identity(source, threading.Event()))
        self.assertEqual(bound["timeline"][0]["start"], 0)
        self.assertEqual(bound["timeline"][0]["end"], 1)
        self.assertEqual(bound["output"]["framing"], "comedy_bands")
        self.assertEqual(bound["captions"][0]["zone"], "top")
        self.assertEqual(template["source"]["name"], "different-long.mp4")
        self.assertNotIn(studio, self.window.auto_children)


if __name__ == "__main__":
    unittest.main()
