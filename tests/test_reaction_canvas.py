from dataclasses import asdict, replace
import unittest

from editor.reaction_geometry import positioned, visual_bounds
from editor.reactions import VisualCue
from editor.pulse_plan import reaction_cues


class ReactionGeometryTests(unittest.TestCase):
    item = dict(width=256, height=256, duration=1)

    def test_v2_positions_round_trip_after_move_and_resize(self):
        for width, height in ((640, 360), (1080, 1920), (1080, 1080)):
            for position in ('centre', 'top_left', 'top_right', 'bottom_left', 'bottom_right'):
                for animation in ('none', 'fade', 'pop', 'spin', 'bounce', 'shake'):
                    cue = VisualCue('emoji', 'emoji.skull', 1, 3, position=position, animation=animation)
                    at = 1.08
                    moved = positioned(cue, width*.3, height*.4, width, height, at, self.item)
                    box = visual_bounds(moved, width, height, at, self.item)
                    self.assertAlmostEqual(box.x, width*.3)
                    self.assertAlmostEqual(box.y, height*.4)
                    resized = positioned(replace(moved, scale=.35), box.x, box.y,
                                         width, height, at, self.item)
                    new = visual_bounds(resized, width, height, at, self.item)
                    self.assertGreater(new.side, box.side)
                    self.assertAlmostEqual(new.x, box.x)
                    self.assertAlmostEqual(new.y, box.y)
                    _, loaded = reaction_cues(dict(overlays=[asdict(resized)]))
                    self.assertEqual(loaded, (resized,))

    def test_extreme_drags_stay_in_normalized_range(self):
        cue = VisualCue('emoji', 'emoji.skull', 0, 2, rotation=145, scale=.6)
        for x, y in ((-5000, -5000), (5000, 5000)):
            moved = positioned(cue, x, y, 1080, 1920, 1, self.item)
            moved.validate(2)
            box = visual_bounds(moved, 1080, 1920, 1, self.item)
            self.assertGreaterEqual(box.x, 0)
            self.assertGreaterEqual(box.y, 0)
            self.assertLessEqual(box.x+box.side, 1080)
            self.assertLessEqual(box.y+box.side, 1920)

    def test_rectangular_gif_padding_and_non_looping_lifetime(self):
        cue = VisualCue('gif', 'import.test', 1, 4, loop=False, scale=97/360)
        item = dict(width=256, height=128, duration=.5)
        box = visual_bounds(cue, 640, 360, 1.3, item)
        self.assertEqual(box.side, 109)  # Actual FFmpeg: fitted 97x49, rotated canvas 109x109.
        self.assertIsNone(visual_bounds(cue, 640, 360, 1.5, item))
        self.assertIsNotNone(visual_bounds(replace(cue, loop=True), 640, 360, 2, item))
        self.assertIsNone(visual_bounds(cue, 640, 360, .9, item))
        self.assertIsNone(visual_bounds(replace(cue, opacity=0), 640, 360, 1.2, item))


if __name__ == '__main__':
    unittest.main()
