"""Cut-aware audio-clock preview latency correction regressions.

Decoder latency changes only the *requested still frame*; media timing and
Quick Edit's exported MP4 audio/video timestamps remain unchanged.
"""
import unittest

from editor.cuts import CutPlan, CutRange
from editor.models import TrimRange
from editor.preview import anticipated_source_position


class PreviewSynchronizationTests(unittest.TestCase):
    def test_frame_predicts_when_it_will_be_displayed(self):
        trim = TrimRange(0, 20)
        self.assertAlmostEqual(
            anticipated_source_position(CutPlan(), trim, 5.0, 1, 1.4), 6.4)

    def test_cut_jump_is_accounted_for_before_decode(self):
        trim = TrimRange(0, 20)
        cuts = CutPlan((CutRange(5, 7),))
        # Output timeline 4.5 + .75 seconds is source time 7.25,
        # not 5.25 seconds inside a removed interval.
        self.assertAlmostEqual(
            anticipated_source_position(cuts, trim, 4.5, 1, .75), 7.25)

    def test_speed_scales_decode_time_in_source_seconds(self):
        trim = TrimRange(0, 20)
        self.assertAlmostEqual(
            anticipated_source_position(CutPlan(), trim, 5.0, 2, 1.25), 7.5)

    def test_preview_correction_does_not_pass_end_of_selection(self):
        trim = TrimRange(3, 9)
        self.assertAlmostEqual(
            anticipated_source_position(CutPlan(), trim, 5.9, 1, 2), 9)

    def test_zero_latency_is_original_playhead(self):
        trim = TrimRange(0, 20)
        self.assertEqual(
            anticipated_source_position(CutPlan(), trim, 5, 1, 0), 5)


if __name__ == '__main__':
    unittest.main()
