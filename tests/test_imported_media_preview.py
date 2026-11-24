"""Direct media manipulation without creating a Tk window or reading files on each move."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from editor.cuts import CutPlan
from editor.edit_history import EditSnapshot
from editor.imported_media import MediaClip, media_bounds
from editor.models import MediaInfo, TrimRange
from editor.reaction_preview import ReactionPreview
from editor.transforms import EditOptions


class FakeMediaCanvas:
    media_ready = ReactionPreview.media_ready
    media_rect = ReactionPreview.media_rect
    output_time = ReactionPreview.output_time
    output_point = ReactionPreview.output_point
    context = ReactionPreview.context
    media_handles = staticmethod(ReactionPreview.media_handles)
    select_media = ReactionPreview.select_media
    begin_media = ReactionPreview.begin_media
    apply_media = ReactionPreview.apply_media
    move_media = ReactionPreview.move_media

    def __init__(self, root):
        source = root / 'capture.mp4'
        picture = root / 'image.png'
        source.write_bytes(b'test')
        picture.write_bytes(b'test')
        media = MediaInfo(source, 20, 640, 360, 30, True)
        clip = MediaClip(str(picture), 'photo', 2., 6.,
                         layout='Picture in picture', source_width=800,
                         source_height=400)
        trim, cuts, edits = TrimRange(0., 20.), CutPlan(), EditOptions(media_clips=(clip,))
        self.window = SimpleNamespace(
            position=3., trim=trim, cuts=cuts, edits=edits, media=media,
            playing=False, closing=False, exporter=SimpleNamespace(busy=False),
            tool=SimpleNamespace(get=lambda: 'TRIM'),
            media_dialog=None, timeline_history=None,
            note=SimpleNamespace(configure=lambda **_kwargs: None))
        self.window.request_frame = lambda: None
        self.media = media
        self.photo = object()
        self.source_view = False
        self.enabled = True
        self.render_context = (3., trim, cuts, replace(edits, overlays=()))
        self.media_drag = None
        self.selected_media_index = None
        self.selected_visual = None
        self.visual_drag = None

    def bounds(self):
        return (0, 0, 640, 360)

    def focus_set(self):
        return None

    def draw_overlay(self):
        return None


class CanvasMediaInteractionTests(unittest.TestCase):
    def setUp(self):
        self.files = TemporaryDirectory()
        self.addCleanup(self.files.cleanup)
        self.canvas = FakeMediaCanvas(Path(self.files.name))

    def event(self, x, y):
        return SimpleNamespace(x=x, y=y)

    def test_click_and_drag_media_updates_position_and_preserves_size(self):
        c = self.canvas
        clip = c.window.edits.media_clips[0]
        box = media_bounds(clip, 640, 360)
        self.assertTrue(c.begin_media(self.event(box.x+20, box.y+20)))
        self.assertEqual(c.selected_media_index, 0)
        self.assertEqual(c.media_drag['mode'], 'move')
        c.move_media(self.event(box.x-65, box.y+75))
        moved = c.window.edits.media_clips[0]
        self.assertLess(moved.x, clip.x)
        self.assertGreater(moved.y, clip.y)
        self.assertEqual(moved.scale, clip.scale)
        c.window.timeline_history.end()
        self.assertEqual(len(c.window.timeline_history.past), 1)

    def test_corner_drag_resizes_with_locked_aspect_ratio(self):
        c = self.canvas
        clip = c.window.edits.media_clips[0]
        box = media_bounds(clip, 640, 360)
        c.select_media(0)
        self.assertTrue(c.begin_media(self.event(box.x, box.y)))
        self.assertEqual(c.media_drag['mode'], 'nw')
        c.move_media(self.event(box.x-25, box.y-25))
        enlarged = c.window.edits.media_clips[0]
        self.assertGreater(enlarged.scale, clip.scale)
        target = media_bounds(enlarged, 640, 360)
        self.assertAlmostEqual(target.width / target.height, 2, delta=.04)

    def test_cutaway_can_be_moved_into_picture_in_picture(self):
        c = self.canvas
        full = replace(c.window.edits.media_clips[0], layout='Cutaway')
        c.window.edits = replace(c.window.edits, media_clips=(full,))
        self.assertTrue(c.begin_media(self.event(100, 100)))
        c.move_media(self.event(300, 160))
        moved = c.window.edits.media_clips[0]
        self.assertEqual(moved.layout, 'Picture in picture')
        self.assertAlmostEqual(moved.scale, .6)
        self.assertGreaterEqual(moved.x, 0)
        self.assertLessEqual(moved.y, 1)

    def test_outside_click_deselects_without_changing_edit_state(self):
        c = self.canvas
        before = c.window.edits
        self.assertFalse(c.begin_media(self.event(20, 300)))
        self.assertIsNone(c.selected_media_index)
        self.assertEqual(c.window.edits, before)


if __name__ == '__main__':
    unittest.main()
