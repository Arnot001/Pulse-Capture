"""Tests for edit-station audio: source, cuts, speed and original/Pulse music."""
from pathlib import Path
import unittest

from editor.audio_preview import audio_preview_command, AudioPlayback
from editor.cuts import CutPlan, CutRange
from editor.models import MediaInfo, TrimRange
from editor.music import Music
from editor.transforms import EditOptions


class EditAudioTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 12, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 11)

    def test_source_preview_uses_trim_position_and_pcm_output(self):
        cmd = audio_preview_command('ffmpeg', self.media, 3, self.trim)
        graph = cmd[cmd.index('-filter_complex')+1]
        self.assertIn('atrim=start=3.000000000:end=11.000000000', graph)
        self.assertIn('aresample=async=1:first_pts=0', graph)
        self.assertEqual(cmd[-1], 'pipe:1')
        self.assertIn('pcm_s16le', cmd)
        self.assertIn('48000', cmd)

    def test_source_follows_removed_sections_and_clip_speed(self):
        cuts = CutPlan((CutRange(4, 7),))
        edits = EditOptions(speed=2)
        cmd = audio_preview_command('ffmpeg', self.media, 3, self.trim, cuts, edits)
        graph = cmd[cmd.index('-filter_complex')+1]
        self.assertIn('atrim=start=3.000000000:end=4.000000000', graph)
        self.assertIn('atrim=start=7.000000000:end=11.000000000', graph)
        self.assertIn('concat=n=2:v=0:a=1', graph)
        self.assertIn('atempo=2', graph)
        self.assertIn('2.500000000', cmd)

    def test_music_is_aligned_to_kept_output_time(self):
        cuts = CutPlan((CutRange(4, 7),))
        music = Music(True, music_volume=.2, original_volume=.5, loop=True)
        edits = EditOptions(music=music, speed=2)
        cmd = audio_preview_command('ffmpeg', self.media, 8, self.trim, cuts, edits,
                                    music_path=Path('music.wav'))
        graph = cmd[cmd.index('-filter_complex')+1]
        self.assertIn('atrim=start=8.000000000:end=11.000000000', graph)
        # 1..4 plus 7..8 = 4 kept seconds; 2x speed -> 2s soundtrack offset
        self.assertIn('atrim=start=2.000000000:end=3.500000000', graph)
        self.assertIn('volume=0.5', graph)
        self.assertIn('volume=0.2', graph)
        self.assertIn('amix=inputs=2', graph)

    def test_music_only_when_source_lacks_audio(self):
        media = MediaInfo(Path('silent.mp4'), 12, 1920, 1080, 30, False)
        self.assertIsNone(audio_preview_command('ffmpeg', media, 1, self.trim))
        edits = EditOptions(music=Music(True))
        cmd = audio_preview_command('ffmpeg', media, 1, self.trim, edits=edits,
                                    music_path=Path('music.wav'))
        self.assertNotIn('[0:a:0]', ' '.join(cmd))
        self.assertIn('1:a:0', ' '.join(cmd))
        self.assertIn('pipe:1', cmd)
        self.assertIn('-stream_loop', cmd)

    def test_preview_stop_and_close_are_idempotent(self):
        # No source audio: no background player or device initialization.
        media = MediaInfo(Path('silent.mp4'), 12, 1920, 1080, 30, False)
        player = AudioPlayback('ffmpeg', media)
        player.play(1, self.trim, CutPlan(), EditOptions())
        player.stop()
        player.close()
        player.stop()
        self.assertIsNone(player._worker)


if __name__ == '__main__':
    unittest.main()
