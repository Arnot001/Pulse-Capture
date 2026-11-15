"""Auto Edit highlight ranking and FFmpeg log parsing (no GPU/API required)."""
import unittest

from editor.auto_plan import choose_highlights
from editor.auto_analysis import parse_scene_log, parse_energy_log


class AutoPlanTests(unittest.TestCase):
    def test_clip_bounds_and_count(self):
        for count in (1, 2, 3):
            suggestions = choose_highlights(
                240, scenes=range(5, 240, 7),
                energy=[(t, -20 if t % 20 < 4 else -55) for t in range(240)],
                style='Gaming', count=count)
            self.assertEqual(len(suggestions), count)
            for item in suggestions:
                self.assertGreaterEqual(item.start, 0)
                self.assertLessEqual(item.end, 240)
                self.assertAlmostEqual(item.duration, 28, places=3)

    def test_short_source_returns_single_whole_clip(self):
        candidates = choose_highlights(15, style='Funny Moments', count=3)
        self.assertEqual(len(candidates), 1)
        self.assertEqual((candidates[0].start, candidates[0].end), (0, 15))

    def test_no_duplicate_overlapping_shorts(self):
        candidates = choose_highlights(180, scenes=range(0,180,5), count=3)
        for index, item in enumerate(candidates):
            for other in candidates[index+1:]:
                overlap = max(0, min(item.end, other.end)-max(item.start, other.start))
                self.assertLessEqual(overlap, 28*.30)

    def test_invalid_inputs_fail_visibly(self):
        for style in ('nope', '', 'news'):
            with self.assertRaises(ValueError):
                choose_highlights(100, style=style)
        for count in (0, 4, 1.2):
            with self.assertRaises(ValueError):
                choose_highlights(100, count=count)
        for duration in (0, -1, float('nan')):
            with self.assertRaises(ValueError):
                choose_highlights(duration)

    def test_parses_source_time_scene_and_audio_metadata(self):
        scenes = ('[Parsed_showinfo_1 @ a] n: 0 pts: 40 pts_time:2.000 pos:1\n'
                  '[Parsed_showinfo_1 @ a] pts_time:8.5')
        self.assertEqual(parse_scene_log(scenes), (2.0, 8.5))
        energy = ('frame:0 pts:0 pts_time:0\n'
                  'lavfi.astats.Overall.RMS_level=-30\n'
                  'frame:1 pts:8000 pts_time:1\n'
                  'lavfi.astats.Overall.RMS_level=-12')
        self.assertEqual(parse_energy_log(energy), ((0, -30), (1, -12)))


if __name__ == '__main__':
    unittest.main()
