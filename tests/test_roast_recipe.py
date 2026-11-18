"""JSON Roast Studio source matching and dark-band behaviour (offline)."""
from copy import deepcopy
from pathlib import Path
import unittest

from editor.models import MediaInfo
from editor.roast_recipe import bind_roast_recipe, inspect_coverage, reference_mismatch


def video(name, duration):
    return MediaInfo(Path(name), duration, 1600, 900, 30.0, True)


def identity(media, marker="b"):
    return dict(name=media.path.name, duration=media.duration,
                width=media.width, height=media.height, fps=media.fps,
                sha256=marker * 64)


def plan_for_original():
    return dict(
        format="pulse-edit-plan", version=2, title="Elevator Fashion Emergency",
        style="Comedy / Roast",
        source=dict(name="long.mp4", duration=20.0, width=1600,
                    height=900, fps=30.0, sha256="a"*64),
        output=dict(width=1080, height=1920, fps=30,
                    framing="full_frame", background="dark"),
        timeline=[
            dict(kind="shot", start=10.0, end=12.0,
                 start_frame=300, end_frame=360, role="setup"),
            dict(kind="freeze", source_time=11.0, duration=1.0, role="punchline"),
            dict(kind="shot", start=12.0, end=13.0, role="replay"),
        ],
        captions=[
            dict(start=0.0, end=1.0, text="IN A LIFT.", zone="top", basis="joke"),
            dict(start=2.0, end=3.0, text="THIS IS NOT VOGUE.", zone="bottom", basis="joke"),
        ],
        caption_theme="Comedy Bold", freeze_duration=1.0,
        sfx=[], overlays=[], notes="An intentionally ridiculous complaint.",
    )


class RoastStudioRecipeTests(unittest.TestCase):
    def test_exact_video_requires_no_override_and_preserves_original(self):
        old = video("long.mp4", 20)
        recipe = plan_for_original()
        snapshot = deepcopy(recipe)
        bound = bind_roast_recipe(recipe, old, identity(old, "a"))
        self.assertEqual(bound["source"]["sha256"], "a"*64)
        self.assertEqual(bound["output"]["framing"], "comedy_bands")
        self.assertEqual(bound["captions"][0]["zone"], "top")
        self.assertEqual(bound["captions"][1]["zone"], "bottom")
        self.assertEqual(bound["timeline"][0]["start"], 10.0)
        self.assertEqual(recipe, snapshot)

    def test_different_duration_or_filename_needs_confirmation(self):
        short = video("shorter.mp4", 12)
        recipe = plan_for_original()
        with self.assertRaisesRegex(ValueError, "Different source"):
            bind_roast_recipe(recipe, short, identity(short), offset=-5)
        self.assertEqual(reference_mismatch(recipe, identity(short)),
                         ["video content hash", "filename", "duration"])
        result = bind_roast_recipe(recipe, short, identity(short), offset=-5,
                                   confirm_mismatch=True)
        self.assertEqual(result["source"]["name"], "shorter.mp4")
        self.assertEqual(result["source"]["duration"], 12)
        self.assertEqual(result["timeline"][0]["start"], 5)
        self.assertEqual(result["timeline"][0]["end"], 7)
        self.assertEqual(result["timeline"][0]["start_frame"], 150)
        self.assertEqual(result["timeline"][0]["end_frame"], 210)
        self.assertEqual(result["timeline"][1]["source_time"], 6)
        self.assertIn("shifted by -5.000s", result["notes"])

    def test_out_of_range_times_rejected_even_with_confirmation(self):
        short = video("shorter.mp4", 9)
        with self.assertRaisesRegex(ValueError, "Element 1 needs source"):
            bind_roast_recipe(plan_for_original(), short, identity(short),
                              confirm_mismatch=True)
        with self.assertRaisesRegex(ValueError, "Source offset"):
            inspect_coverage(plan_for_original(), short, float("nan"))

    def test_rebind_never_forges_unknown_video_hash(self):
        old = video("long.mp4", 20)
        with self.assertRaisesRegex(ValueError, "fingerprint does not belong"):
            bind_roast_recipe(plan_for_original(), old, identity(video("other.mp4", 20)))
        broken = identity(old)
        broken["sha256"] = "?"
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            bind_roast_recipe(plan_for_original(), old, broken, confirm_mismatch=True)

    def test_non_v2_json_rejected_instead_of_best_effort(self):
        p = plan_for_original()
        p["version"] = 1
        with self.assertRaisesRegex(ValueError, "v2"):
            inspect_coverage(p, video("long.mp4", 20))

    def test_dark_bands_reject_unreadably_long_caption(self):
        p = plan_for_original()
        p["captions"][1]["text"] = "ABSURDLY LONG " * 30
        with self.assertRaises((ValueError,)):
            bind_roast_recipe(p, video("long.mp4", 20),
                              identity(video("long.mp4", 20), "a"))

    def test_matching_name_without_matching_bytes_still_requires_review(self):
        video_now = video("long.mp4", 20)
        with self.assertRaisesRegex(ValueError, "video content hash"):
            bind_roast_recipe(plan_for_original(), video_now,
                              identity(video_now, "b"))


if __name__ == "__main__":
    unittest.main()
