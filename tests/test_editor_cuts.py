from dataclasses import replace
from pathlib import Path
import unittest

from editor.cuts import CutPlan, CutRange
from editor.ffmpeg_export import build_export_command
from editor.models import MediaInfo, TrimRange
from editor.polish import Fade, Zoom
from editor.preview import preview_command
from editor.transforms import EditOptions


class CutPlanTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 10, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 9)

    def test_sorted_kept_segments_mapping_and_restore(self):
        plan = CutPlan().add(CutRange(4, 5), self.media)
        plan = plan.add(CutRange(2, 3), self.media)
        self.assertEqual(plan.ranges, (CutRange(2, 3), CutRange(4, 5)))
        self.assertEqual(
            plan.kept_segments(self.trim),
            (TrimRange(1, 2), TrimRange(3, 4), TrimRange(5, 9)),
        )
        self.assertAlmostEqual(plan.kept_duration(self.trim), 6)
        self.assertAlmostEqual(plan.removed_duration(self.trim), 2)
        self.assertAlmostEqual(plan.source_elapsed(3.5, self.trim), 1.5)
        self.assertAlmostEqual(plan.source_from_elapsed(1.5, self.trim), 3.5)
        self.assertAlmostEqual(plan.snap_position(2.5, self.trim), 3.0)
        restored = plan.remove(CutRange(2, 3))
        self.assertEqual(restored.ranges, (CutRange(4, 5),))

    def test_visible_ranges_clip_to_trim(self):
        plan = CutPlan((CutRange(0, 2), CutRange(4, 5), CutRange(8, 10)))
        plan.validate(self.media)
        self.assertEqual(
            plan.visible_ranges(self.trim),
            (CutRange(1, 2), CutRange(4, 5), CutRange(8, 9)),
        )
        self.assertEqual(plan.kept_segments(self.trim), (TrimRange(2, 4), TrimRange(5, 8)))
        self.assertAlmostEqual(plan.kept_duration(self.trim), 5)

    def test_overlap_invalid_restore_and_remove_everything_are_rejected(self):
        plan = CutPlan().add(CutRange(2, 4), self.media)
        with self.assertRaises(ValueError):
            plan.add(CutRange(3, 5), self.media)
        with self.assertRaises(ValueError):
            plan.remove(CutRange(7, 8))
        with self.assertRaises(ValueError):
            CutPlan((CutRange(1, 9),)).validate_selection(self.media, self.trim)


class CutCommandTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaInfo(Path('source.mp4'), 10, 1920, 1080, 30, True)
        self.trim = TrimRange(1, 9)
        self.cuts = CutPlan((CutRange(2, 3), CutRange(5, 6)))

    def command(self, edits=EditOptions(), media=None):
        return build_export_command(
            'ffmpeg', media or self.media, self.trim, 'edited.mp4', edits, cuts=self.cuts
        )

    def test_audio_cut_export_uses_trim_concat_before_visual_filters(self):
        cmd = self.command()
        self.assertNotIn('-ss', cmd)
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('[0:v:0]trim=start=1.000000000:end=2.000000000', graph)
        self.assertIn('[0:v:0]trim=start=3.000000000:end=5.000000000', graph)
        self.assertIn('[0:v:0]trim=start=6.000000000:end=9.000000000', graph)
        self.assertIn('[0:a:0]atrim=start=1.000000000:end=2.000000000', graph)
        self.assertIn('concat=n=3:v=1:a=1[cutv][cuta]', graph)
        self.assertLess(graph.index('concat=n=3'), graph.index('[cutv]pad='))
        self.assertIn('-map', cmd)
        self.assertIn('[v]', cmd)

    def test_silent_cut_export_stays_silent(self):
        silent = replace(self.media, has_audio=False)
        cmd = self.command(media=silent)
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('concat=n=3:v=1:a=0[cutv]', graph)
        self.assertNotIn('[0:a:0]', graph)
        self.assertIn('-an', cmd)

    def test_speed_fades_use_post_cut_duration(self):
        edits = EditOptions(speed=2.0, fade=Fade(True, True))
        cmd = self.command(edits)
        graph = cmd[cmd.index('-filter_complex') + 1]
        # Eight source seconds minus two one-second cuts = six kept seconds;
        # 2x speed makes a three-second output.
        self.assertIn('setpts=PTS/2', graph)
        self.assertIn('fade=t=out:st=2.500000:d=0.500000', graph)
        self.assertIn('atempo=2', graph)
        self.assertIn('afade=t=out:st=2.500000:d=0.500000', graph)

    def test_full_clip_zoom_preview_uses_kept_output_time(self):
        edits = EditOptions(
            zoom=Zoom(
                enabled=True, factor=1.5, focus_x=.6, focus_y=.4,
                mode='Zoom in', motion_speed='Full clip',
            ),
            speed=2.0,
        )
        # At source time 7, four kept source seconds have elapsed. At 2x
        # playback that is output time 2.0s, while the full output lasts 3.0s.
        cmd = preview_command(
            'ffmpeg', self.media, 7, 640, 360, edits, False,
            trim=self.trim, cuts=self.cuts,
        )
        graph = cmd[cmd.index('-filter_complex') + 1]
        self.assertIn('2.000000000', graph)
        self.assertIn('/3.000000000', graph)


if __name__ == '__main__':
    unittest.main()
