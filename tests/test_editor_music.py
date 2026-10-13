from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from editor.cuts import CutPlan, CutRange
from editor.ffmpeg_export import build_export_command
from editor.models import MediaInfo, TrimRange
from editor.music import (
    IMPORT_LABEL, Music, TRACKS, VOLUME_LEVELS, generate_track, music_duration,
)
from editor.transforms import Branding, EditOptions


class MusicModelTests(unittest.TestCase):
    def test_library_and_defaults(self):
        self.assertEqual(
            tuple(TRACKS),
            (
                'Pulse // Night', 'Pulse // Drive', 'Pulse // Focus',
                'Pulse // Lift', 'Pulse // Horizon', 'Pulse // Circuit',
            ),
        )
        music = Music()
        music.validate()
        self.assertFalse(music.enabled)
        self.assertEqual(music.music_volume, .20)
        self.assertEqual(music.original_volume, 1.0)
        self.assertTrue(music.loop)
        self.assertTrue(music.fade_in)
        self.assertTrue(music.fade_out)
        self.assertTrue(all(0 <= value <= 1 for value in VOLUME_LEVELS))
        self.assertGreater(music_duration('Pulse // Night'), 10)

    def test_invalid_tracks_volumes_and_imports(self):
        for music in (
            Music(track='Unknown'),
            Music(music_volume=-.1),
            Music(original_volume=1.1),
            Music(track=IMPORT_LABEL),
            Music(track=IMPORT_LABEL, imported=Path('track.txt')),
        ):
            with self.subTest(music=music), self.assertRaises(ValueError):
                music.validate()

        Music(track=IMPORT_LABEL, imported=Path('track.mp3')).validate()
        Music(track=IMPORT_LABEL, imported=Path('track.wav')).validate()

    def test_generator_is_deterministic_and_valid_wav(self):
        with TemporaryDirectory() as folder, patch('editor.music.BARS', .08):
            first = Path(folder) / 'one.wav'
            second = Path(folder) / 'two.wav'
            generate_track('Pulse // Focus', first)
            generate_track('Pulse // Focus', second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertTrue(first.read_bytes().startswith(b'RIFF'))
            self.assertGreater(first.stat().st_size, 1000)


class MusicCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'source.mp4'
        self.source.touch()
        self.music_path = self.folder / 'music.wav'
        self.music_path.touch()
        self.media = MediaInfo(self.source, 10, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 5)

    def music(self, **changes):
        base = Music(
            enabled=True,
            track=IMPORT_LABEL,
            imported=self.music_path,
            music_volume=.20,
            original_volume=.75,
            loop=True,
            fade_in=True,
            fade_out=True,
        )
        return replace(base, **changes)

    def command(self, music=None, media=None, edits=None, cuts=None, brand=False):
        media = media or self.media
        edits = edits or EditOptions(music=music or self.music())
        if brand:
            edits = replace(edits, branding=Branding(True))
        return build_export_command(
            'ffmpeg', media, self.trim, self.folder / 'out.mp4', edits,
            asset=self.music_path, cuts=cuts or CutPlan(), music_path=self.music_path,
        )

    def test_source_audio_mix_loop_volumes_and_fades(self):
        cmd = self.command()
        joined = ' '.join(map(str, cmd))
        self.assertIn('-stream_loop -1', joined)
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('[0:a:0]volume=0.75[sourcea]', graph)
        self.assertIn('[1:a:0]asetpts=PTS-STARTPTS,volume=0.2', graph)
        self.assertIn('afade=t=in:st=0:d=0.500000', graph)
        self.assertIn('afade=t=out:st=3.500000:d=0.500000', graph)
        self.assertIn('amix=inputs=2:duration=longest:dropout_transition=0', graph)
        self.assertIn('-map', cmd)
        self.assertIn('[a]', cmd)
        self.assertNotIn('-an', cmd)

    def test_silent_source_gets_music_audio(self):
        media = replace(self.media, has_audio=False)
        cmd = self.command(media=media)
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertNotIn('[0:a:0]', graph)
        self.assertIn('[1:a:0]asetpts=PTS-STARTPTS', graph)
        self.assertIn('[musica]anull[a]', graph)
        self.assertNotIn('-an', cmd)

    def test_no_loop_pads_music_to_output(self):
        cmd = self.command(self.music(loop=False, fade_in=False, fade_out=False))
        self.assertNotIn('-stream_loop', cmd)
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('apad=pad_dur=4.000000', graph)
        self.assertIn('atrim=start=0:end=4.000000', graph)

    def test_branding_keeps_music_on_third_input(self):
        cmd = self.command(brand=True)
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('[1:v:0]scale=', graph)
        self.assertIn('[2:a:0]asetpts=PTS-STARTPTS', graph)

    def test_cut_speed_mix_uses_post_cut_output_duration(self):
        cuts = CutPlan((CutRange(2, 3),))
        edits = EditOptions(music=self.music(), speed=2.0)
        cmd = self.command(edits=edits, cuts=cuts)
        graph = cmd[cmd.index('-filter_complex') + 1]
        # Four selected seconds minus one cut = three kept; 2x -> 1.5 output seconds.
        self.assertIn('atempo=2', graph)
        self.assertIn('atrim=start=0:end=1.500000', graph)
        self.assertIn('afade=t=out:st=1.000000:d=0.500000', graph)

    def test_music_off_preserves_legacy_silent_behavior(self):
        media = replace(self.media, has_audio=False)
        edits = EditOptions(music=Music(enabled=False, original_volume=.10))
        cmd = build_export_command(
            'ffmpeg', media, self.trim, self.folder / 'out.mp4', edits
        )
        self.assertIn('-an', cmd)
        self.assertNotIn('-stream_loop', cmd)
        self.assertNotIn('volume=0.1', ' '.join(map(str, cmd)))


if __name__ == '__main__':
    unittest.main()
