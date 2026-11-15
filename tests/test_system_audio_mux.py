"""Regression tests for real GTA VI audio leading video by ~0.90 seconds."""
import math
import unittest

from capture.system_audio_mux import measured_sync_offset, merge_command


class SyncOffsetTests(unittest.TestCase):
    def test_measured_preroll_replaces_delayed_ffmpeg_progress_guess(self):
        # Representative capture: a 33.033s WASAPI WAV, 32.333s video.
        # Previous guessed offset of 1.600s would leave only 31.433s of
        # audio and shift spoken dialogue about 0.9 seconds too early.
        video = 32.333333
        wav = 33.033333
        prior_guess = 1.6
        self.assertAlmostEqual(wav - prior_guess, 31.433333, places=3)
        offset = measured_sync_offset(wav, video)
        self.assertAlmostEqual(offset, 0.7, places=6)
        self.assertAlmostEqual(wav - offset, video, places=6)
        command = merge_command('ffmpeg', 'video.mp4', 'source.wav',
                                'result.mp4', video, False, offset)
        self.assertIn('-ss', command)
        self.assertEqual(command[command.index('-ss')+1], '0.700000')

    def test_negative_offset_delays_late_starting_audio(self):
        offset = measured_sync_offset(19.6, 20)
        self.assertAlmostEqual(offset, -.4, places=6)
        command = merge_command('ffmpeg', 'video.mp4', 'source.wav',
                                'result.mp4', 20, False, offset)
        self.assertIn('-itsoffset', command)
        self.assertEqual(command[command.index('-itsoffset')+1], '0.400000')

    def test_equal_spans_do_not_force_audio_shift(self):
        self.assertEqual(measured_sync_offset(30, 30), 0)

    def test_refuse_broken_audio_clocks_not_mask_with_shift(self):
        for audio, video in ((float('nan'), 30), (30, float('inf')),
                             (0, 30), (30, 0), (2, 30)):
            with self.subTest(audio=audio, video=video):
                with self.assertRaises(RuntimeError):
                    measured_sync_offset(audio, video)


if __name__ == '__main__':
    unittest.main()
