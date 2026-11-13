"""A/V sync regression cases from a real 30.93s/18.77s Shorts export."""
import time
import unittest

from capture.ffmpeg_backend import validate_audio_coverage
from editor.audio_preview import AudioPlayback
from editor.models import MediaInfo
from pathlib import Path


def packet_info(video, audio):
    return {
        'format': {'duration': str(video)},
        'streams': [
            {'codec_type': 'video', 'duration': str(video)},
            {'codec_type': 'audio', 'duration': str(audio)},
        ],
    }


class SyncChecks(unittest.TestCase):
    def test_rejects_real_observed_12_second_missing_audio(self):
        with self.assertRaisesRegex(RuntimeError, 'Audio ended at 18.77s'):
            validate_audio_coverage(packet_info(30.933333, 18.773250))

    def test_accepts_normal_aac_encoder_padding(self):
        validate_audio_coverage(packet_info(30.933333, 30.90))
        validate_audio_coverage(packet_info(30.933333, 30.5))

    def test_rejects_missing_audio_or_video(self):
        for info in ({'format': {'duration': '30'}, 'streams': []},
                     packet_info(30, 0)):
            with self.subTest(info=info), self.assertRaises(RuntimeError):
                validate_audio_coverage(info)

    def test_audio_master_clock_waits_for_first_pcm(self):
        media = MediaInfo(Path('recording.mp4'), 40, 1920, 1080, 30, True)
        player = AudioPlayback('ffmpeg', media)
        try:
            self.assertIsNone(player.elapsed())
            with player._lock:
                player._audio_clock_start = time.monotonic() - 2
            self.assertAlmostEqual(player.elapsed(), 2.0, delta=.1)
            player.stop()
            self.assertIsNone(player.elapsed())
        finally:
            player.close()


if __name__ == '__main__':
    unittest.main()
