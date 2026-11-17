"""Canvas gestures, dialog values and decoded preview/export agreement."""
from dataclasses import asdict, replace
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import run
from editor.models import TrimRange
from editor.cuts import CutPlan, CutRange
from editor.reaction_library import ReactionLibrary
from editor.reaction_tools import ReactionDialog
from editor.reactions import SoundCue, VisualCue
from editor.preview import preview_command
from editor.text_overlay import TextResources, TextOverlay, Caption
from editor.typography import CaptionStyle
from editor.transforms import FULL_FRAME_FORMAT
from editor.pulse_plan import reaction_cues
from tests import test_pulse_plan_ui as fixture


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1', 'Opt-in Windows Tk integration')
class ReactionCanvasUITests(unittest.TestCase):
    cleanup = fixture.PulsePlanUITests.cleanup
    pump = fixture.PulsePlanUITests.pump

    def setUp(self):
        fixture.PulsePlanUITests.setUp(self)
        self.library_env = patch.dict(os.environ, PULSE_REACTION_LIBRARY=str(self.folder/'library'))
        self.library_env.start()
        self.addCleanup(self.library_env.stop)

    def picture(self, action):
        old = self.window.video.photo
        action()
        self.pump(lambda: self.window.video.photo is not old)

    def overlay(self, kind='emoji', asset='emoji.skull'):
        w = self.window
        dialog = ReactionDialog(w, kind)
        dialog.assets.selection_set(asset)
        dialog.values['start'].set('1')
        dialog.values['end'].set('3')
        dialog.animation.set('none')
        dialog.save(False)
        self.assertEqual(len(w.edits.overlays), 1, dialog.note.cget('text'))
        self.picture(lambda: w.seek(1.4))
        dialog.position_on_video()
        self.pump(lambda: w.video.visual_ready())
        return dialog

    def gesture(self, start, finish, release=True):
        canvas = self.window.video
        canvas.event_generate('<Button-1>', x=round(start[0]), y=round(start[1]))
        canvas.event_generate('<B1-Motion>', x=round(finish[0]), y=round(finish[1]))
        if release:
            canvas.event_generate('<ButtonRelease-1>', x=round(finish[0]), y=round(finish[1]))
        self.root.update()

    def test_move_resize_rotate_numeric_update_v2_and_export(self):
        w = self.window
        w.format_choice.set(FULL_FRAME_FORMAT)
        self.picture(w.format_changed)
        dialog = self.overlay()
        video = w.video
        sounds = (SoundCue('comedy.pop', 1),)
        captions = TextOverlay(captions=(Caption(1, 3, 'STILL HERE', 'Top', CaptionStyle()),))
        w.edits = replace(w.edits, sounds=sounds, text=captions)
        self.picture(w.request_frame)
        original = w.edits.overlays[0]
        x1, y1, x2, y2 = video.visual_rect(original)
        self.gesture(((x1+x2)/2, (y1+y2)/2), ((x1+x2)/2-20, (y1+y2)/2-25))
        moved = w.edits.overlays[0]
        self.assertIsNotNone(moved.x)
        self.assertIsNotNone(moved.y)
        self.assertAlmostEqual(float(dialog.values['x'].get()), moved.x, places=8)
        self.assertAlmostEqual(float(dialog.values['y'].get()), moved.y, places=8)
        x1, y1, x2, y2 = video.visual_rect(moved)
        self.gesture((x2, y2), (x2+15, y2+15))
        resized = w.edits.overlays[0]
        self.assertGreater(resized.scale, moved.scale)
        self.assertAlmostEqual(float(dialog.values['scale'].get()), resized.scale, places=8)
        x1, y1, x2, y2 = video.visual_rect(resized)
        _, rx, ry = video.handles((x1, y1, x2, y2))[-1]
        self.gesture((rx, ry), (x2+18, (y1+y2)/2))
        rotated = w.edits.overlays[0]
        self.assertGreater(abs(rotated.rotation), 60)
        self.assertAlmostEqual(float(dialog.values['rotation'].get()), rotated.rotation, places=6)
        self.assertEqual(w.edits.sounds, sounds)
        self.assertEqual(w.edits.text, captions)
        w.open_reactions('emoji')
        self.assertEqual(len([c for c in w.auto_children if isinstance(c, ReactionDialog)]), 1)
        # Existing numeric controls still update the same cue, not a duplicate.
        dialog.values['x'].set('.25')
        dialog.save(True)
        self.assertEqual(len(w.edits.overlays), 1)
        self.assertEqual(w.edits.overlays[0].x, .25)
        self.assertIs(video.selected_visual, w.edits.overlays[0])
        _, restored = reaction_cues(json.loads(json.dumps(dict(overlays=[asdict(w.edits.overlays[0])]))))
        self.assertEqual(restored, w.edits.overlays)
        dialog.withdraw()
        w.update_trim(TrimRange(0, 3))
        w.output_folder = self.folder
        w.export()
        self.pump(lambda: w.last_export is not None)
        # Editing guides are Canvas items only. Actual rendered pixels agree.
        with TextResources(w.edits.text) as resources:
            preview = subprocess.run(preview_command(w.backend.ffmpeg, w.media, 1.4, 360, 640,
                                     w.edits, False, resources, w.trim, w.cuts), capture_output=True, timeout=30)
        exported = subprocess.run([w.backend.ffmpeg, '-v', 'error', '-ss', '1.4', '-i', str(w.last_export),
                                   '-vf', 'scale=360:640', '-frames:v', '1', '-pix_fmt', 'rgb24',
                                   '-f', 'rawvideo', '-'], capture_output=True, timeout=30)
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertEqual(exported.returncode, 0, exported.stderr)
        pixels = preview.stdout.split(b'\n', 3)[-1]
        self.assertEqual(len(pixels), len(exported.stdout))
        self.assertLess(sum(abs(a-b) for a, b in zip(pixels, exported.stdout))/len(pixels), 4)

    def test_gif_drag_resize_cancel_and_cue_file_persistence(self):
        w = self.window
        path = self.folder/'wide.gif'
        result = run([w.backend.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                      'testsrc2=s=120x60:r=10', '-t', '0.5', str(path)], 30)
        self.assertEqual(result.returncode, 0, result.stderr)
        asset = ReactionLibrary().import_file(path, 'gif', w.backend.ffmpeg, w.backend.ffprobe)
        dialog = self.overlay('gif', asset)
        video = w.video
        before = w.edits.overlays[0]
        x1, y1, x2, y2 = video.visual_rect(before)
        self.gesture(((x1+x2)/2, (y1+y2)/2), (x1-40, y1-20), release=False)
        self.assertNotEqual(w.edits.overlays[0], before)
        video.cancel_visual_drag()
        self.assertEqual(w.edits.overlays[0], before)
        self.gesture((x2, y2), (x2+25, y2+25))
        saved = w.edits.overlays
        self.assertTrue(saved[0].loop)
        cue_file = self.folder/'cues.json'
        with patch('editor.reaction_tools.filedialog.asksaveasfilename', return_value=str(cue_file)):
            dialog.save_cues()
        dialog.remove()
        self.assertEqual(w.edits.overlays, ())
        self.assertIsNone(video.selected_visual)
        with patch('editor.reaction_tools.filedialog.askopenfilename', return_value=str(cue_file)):
            dialog.load_cues()
        self.assertEqual(w.edits.overlays, saved)
        # Selecting an expired, non-looping GIF seeks back into its visible span.
        dialog.cues.selection_set(0)
        dialog.select_cue()
        dialog.loop.set(False)
        dialog.save(True)
        self.picture(lambda: w.seek(2.5))
        self.assertIsNone(video.visual_rect(w.edits.overlays[0]))
        self.picture(dialog.position_on_video)
        self.assertIsNotNone(video.visual_rect(w.edits.overlays[0]))

    def test_timing_topmost_selection_and_protected_tools(self):
        w = self.window
        self.overlay()
        video = w.video
        base = replace(w.edits.overlays[0], x=.3, y=.3)
        top = replace(base, asset_id='emoji.laugh')
        w.edits = replace(w.edits, overlays=(base, top))
        self.picture(w.request_frame)
        x1, y1, x2, y2 = video.visual_rect(base)
        self.gesture(((x1+x2)/2, (y1+y2)/2), ((x1+x2)/2, (y1+y2)/2))
        self.assertEqual(video.visual_index(), 1)
        original = w.edits.overlays
        for tool in ('CROP', 'PRIVACY', 'MOTION'):
            self.picture(lambda: w.select_tool(tool))
            self.assertFalse(video.visual_ready())
            self.assertFalse(video.find_withtag('visual-guide'))
            self.assertEqual(w.edits.overlays, original)
        self.picture(lambda: w.select_tool('FORMAT'))
        self.picture(lambda: w.seek(3.2))
        self.assertIsNone(video.visual_rect(base))
        self.assertFalse(video.find_withtag('visual-guide'))
        # Output-time cues still select the right picture after cuts and speed.
        w.cuts = CutPlan((CutRange(1, 2),))
        w.edits = replace(w.edits, speed=2)
        self.picture(lambda: w.seek(3.8))
        self.assertAlmostEqual(video.output_time(), 1.4)
        self.assertIsNotNone(video.visual_rect(base))
        w.exporter.busy = True
        try:
            video.draw_overlay()
            self.assertFalse(video.visual_ready())
            self.assertFalse(video.find_withtag('visual-guide'))
        finally:
            w.exporter.busy = False

    def test_small_overlay_drag_and_stale_gesture_after_seek(self):
        w = self.window
        w.format_choice.set(FULL_FRAME_FORMAT)
        self.picture(w.format_changed)
        dialog = self.overlay()
        dialog.values['scale'].set('.05')
        dialog.save(True)
        self.picture(w.request_frame)
        video = w.video
        x1, y1, x2, y2 = video.visual_rect(w.edits.overlays[0])
        self.gesture(((x1+x2)/2, (y1+y2)/2), ((x1+x2)/2-20, (y1+y2)/2-20), release=False)
        self.assertEqual(w.edits.overlays[0].scale, .05)
        self.assertIsNotNone(w.edits.overlays[0].x)
        saved = w.edits.overlays
        w.seek(4)
        video.event_generate('<B1-Motion>', x=10, y=10)
        video.event_generate('<ButtonRelease-1>', x=10, y=10)
        self.root.update()
        self.assertEqual(w.edits.overlays, saved)
        self.assertIsNone(video.visual_drag)


if __name__ == '__main__':
    unittest.main()
