"""Windows loopback clock-gap tests (no audio hardware or external services)."""
import unittest

from capture.wasapi_loopback import FRAMES, missing_loopback_frames


class LoopbackClockTests(unittest.TestCase):
    def test_ignores_normal_packet_jitter(self):
        rate = 48000
        # First 1024-frame block arrives after 21.33 ms.
        self.assertEqual(missing_loopback_frames(
            10 + FRAMES/rate, 10, 0, FRAMES, rate), 0)
        # A small ~50ms scheduling delay is not a lost-audio gap.
        self.assertEqual(missing_loopback_frames(
            10.08, 10, 0, FRAMES, rate), 0)

    def test_restores_mid_capture_silence_before_later_sound(self):
        rate = 48000
        first = FRAMES
        # After first block, no loopback samples arrive for ~half a second.
        missing = missing_loopback_frames(
            10.55, 10, first, FRAMES, rate)
        self.assertGreater(missing, 0.4 * rate)
        # This much zero PCM must be inserted *before* the next audio block,
        # otherwise later sounds play far earlier than their video frames.
        self.assertLess(missing, 0.55 * rate)

    def test_no_negative_padding_if_reads_get_ahead(self):
        self.assertEqual(missing_loopback_frames(
            10.20, 10, 20000, FRAMES, 48000), 0)

    def test_large_gap_expresses_missing_time_in_pcm_frames(self):
        rate = 48000
        written = 2 * rate
        gap = missing_loopback_frames(13.3, 10, written, FRAMES, rate)
        self.assertAlmostEqual(gap/rate, 1.3 - FRAMES/rate, delta=0.03)


if __name__ == '__main__':
    unittest.main()
