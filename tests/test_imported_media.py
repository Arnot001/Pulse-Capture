"""Photo/video timeline regressions: no external media or network needed."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from editor.cuts import CutPlan, CutRange
from editor.imported_media import MediaClip, add_media, create_clip, validate_clips
from editor.models import MediaInfo, TrimRange
from editor.transforms import EditOptions
from editor.timeline_edits import blocks, change_timing, duration
from editor.edit_history import EditSnapshot
from editor.ffmpeg_export import build_export_command
from editor.playback_preview import playback_command
from editor.preview import preview_command


class MediaTimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.photo = root / 'an image.png'
        self.photo.write_bytes(b'fixture')
        self.video = root / 'some b-roll.mp4'
        self.video.write_bytes(b'fixture')
        self.source = root / 'capture.mp4'
        self.source.write_bytes(b'fixture')
        self.media = MediaInfo(self.source, 20, 640, 360, 30, True)
        self.trim = TrimRange(0, 20)

    def photo_clip(self, **kwargs):
        return replace(MediaClip(str(self.photo), 'photo', 2., 5.), **kwargs)

    def video_clip(self, **kwargs):
        return replace(MediaClip(str(self.video), 'video', 4., 7., 1., 12.), **kwargs)

    def test_photo_import_probes_dimensions_and_limits_duration(self):
        response = SimpleNamespace(returncode=0, stdout='{"streams":[{"width":800,"height":500}]}')
        with patch('editor.imported_media.run', return_value=response) as run:
            clip = create_clip('ffprobe', self.photo, 18., 20.)
            self.assertEqual((clip.kind, clip.start, clip.end), ('photo', 18., 20.))
            run.assert_called_once()
        self.assertEqual(clip.layout, 'Cutaway')

    def test_video_import_checks_duration_and_ignores_imported_audio(self):
        with patch('editor.imported_media.probe_media', return_value=MediaInfo(self.video, 3., 800, 450, 25, True)):
            clip = create_clip('ffprobe', self.video, 5., 20.)
        self.assertEqual((clip.start, clip.end, clip.source_duration), (5., 8., 3.))
        self.assertEqual(clip.kind, 'video')

    def test_rejects_missing_files_invalid_source_ranges_and_output_bounds(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.photo_clip(end=25).validate(20)
        with self.assertRaisesRegex(ValueError, 'remaining'):
            self.video_clip(end=18).validate(20)
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.photo_clip(path=str(self.photo)+'absent').validate(20)
        with self.assertRaisesRegex(ValueError, 'Photos'):
            self.photo_clip(source_in=1).validate(20)
        with self.assertRaises(ValueError):
            validate_clips(tuple(self.photo_clip() for _ in range(17)), 20)

    def test_media_blocks_occupy_dedicated_track_and_support_drag(self):
        state = EditSnapshot(self.trim, CutPlan(), EditOptions(media_clips=(self.photo_clip(),)))
        timeline = blocks(state)
        media_blocks = [b for b in timeline if b.kind == 'media']
        self.assertEqual(len(media_blocks), 1)
        self.assertEqual(media_blocks[0].track, 1)
        self.assertEqual(media_blocks[0].key, ('media', 0))
        moved = change_timing(state, ('media', 0), 7., 10., self.media)
        self.assertEqual((moved.edits.media_clips[0].start, moved.edits.media_clips[0].end), (7., 10.))
        resized = change_timing(state, ('media', 0), 2., 8., self.media)
        self.assertAlmostEqual(resized.edits.media_clips[0].duration, 6)
        self.assertEqual(state.edits.media_clips[0].duration, 3)

    def test_video_drag_cannot_extend_past_source_or_output(self):
        state = EditSnapshot(self.trim, CutPlan(), EditOptions(media_clips=(self.video_clip(),)))
        with self.assertRaisesRegex(ValueError, 'remaining'):
            change_timing(state, ('media', 0), 4., 17., self.media)
        with self.assertRaisesRegex(ValueError, 'output'):
            change_timing(state, ('media', 0), 19., 21., self.media)

    def test_media_compositor_preserves_background_on_inactive_timing(self):
        args = ['ffmpeg', '-i', 'capture.mp4']
        graph = []
        label = add_media(args, graph, 'v', (self.photo_clip(),), 640, 360, sample_time=1.)
        self.assertEqual(label, 'v')
        self.assertEqual(args.count('-i'), 1)
        self.assertEqual(graph, [])

    def test_photo_overlay_and_video_seek_align_to_output_clock(self):
        args = ['ffmpeg', '-i', 'capture.mp4']
        graph = []
        label = add_media(args, graph, 'v', (self.photo_clip(), self.video_clip()), 640, 360,
                          offset=5.)
        self.assertEqual(label, 'mediav1')
        self.assertEqual(args.count('-i'), 2)  # photo ended at 5s; only video is active
        self.assertIn('-ss', args)
        self.assertAlmostEqual(float(args[args.index('-ss')+1]), 2.)  # in=1 + elapsed=1
        self.assertIn('PTS-STARTPTS+5.000000000/TB', ';'.join(graph))
        self.assertIn('lt(t,7.000000000)', ';'.join(graph))

    def test_export_compiles_cutaway_and_picture_in_picture_without_new_audio_stream(self):
        edits = EditOptions(media_clips=(self.photo_clip(), self.video_clip(layout='Picture in picture')))
        cmd = build_export_command('ffmpeg', self.media, self.trim, self.source.parent/'output.mp4', edits)
        graph = cmd[cmd.index('-filter_complex')+1]
        self.assertEqual(cmd.count('-i'), 3)
        self.assertIn('mediav0', graph)
        self.assertIn('mediav1', graph)
        self.assertIn('force_original_aspect_ratio=decrease', graph)
        self.assertIn('W-w-16', graph)
        self.assertIn('0:a:0', cmd)
        self.assertNotIn(str(self.source.parent/'output.mp4')+'-source', cmd)

    def test_still_preview_shows_media_after_cut_and_speed(self):
        trim = TrimRange(2., 20.)
        cuts = CutPlan((CutRange(8., 10.),))
        # At source 6s, elapsed kept = 4s. At 2x speed output is 2s.
        photo = self.photo_clip(start=1., end=3.)
        edits = EditOptions(speed=2., media_clips=(photo,))
        cmd = preview_command('ffmpeg', self.media, 6., 320, 180, edits, False,
                              trim=trim, cuts=cuts)
        self.assertEqual(cmd.count('-i'), 2)
        self.assertIn('mediav0', cmd[cmd.index('-filter_complex')+1])

    def test_continuous_preview_seeks_into_video_not_restarting_it(self):
        trim = TrimRange(0., 20.)
        edits = EditOptions(media_clips=(self.video_clip(),))
        cmd = playback_command('ffmpeg', self.media, 5., 9., trim, CutPlan(), edits,
                               320, 180, None)
        self.assertEqual(cmd.count('-i'), 2)
        self.assertAlmostEqual(float(cmd[cmd.index('-ss', cmd.index('-i')+1)+1]), 2.)
        self.assertIn('mediav0', cmd[cmd.index('-filter_complex')+1])

    def test_media_is_non_destructive(self):
        before_photo = self.photo.read_bytes()
        before_video = self.video.read_bytes()
        edits = EditOptions(media_clips=(self.photo_clip(), self.video_clip()))
        _ = build_export_command('ffmpeg', self.media, self.trim, self.source.parent/'new.mp4', edits)
        self.assertEqual(self.photo.read_bytes(), before_photo)
        self.assertEqual(self.video.read_bytes(), before_video)


if __name__ == '__main__':
    unittest.main()
