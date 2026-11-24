"""Pure deletion and history checks for timeline right-click/keyboard removal."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from editor.crop_motion import CropKeyframe, CropMotion
from editor.cuts import CutPlan
from editor.edit_history import EditHistory, EditSnapshot
from editor.imported_media import MediaClip
from editor.models import MediaInfo, TrimRange
from editor.music import Music
from editor.polish import Zoom
from editor.reactions import SoundCue, VisualCue
from editor.text_overlay import Caption, TextOverlay
from editor.timeline_edits import blocks, remove_blocks
from editor.transforms import EditOptions, SHORTS_FORMAT


class TimelineDeleteTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root/'original.mp4'
        self.source.write_bytes(b'original-data')
        self.photo = self.root/'funny-photo.png'
        self.photo.write_bytes(b'untouched-image')
        self.media = MediaInfo(self.source, 20, 640, 360, 30, True)
        self.trim = TrimRange(0.,20.)

    def state(self, **changes):
        return EditSnapshot(self.trim, CutPlan(), replace(EditOptions(), **changes))

    def test_remove_one_photo_preserves_other_and_original_file(self):
        first = MediaClip(str(self.photo),'photo',1.,3.)
        second = replace(first,start=5.,end=8.)
        state = self.state(media_clips=(first,second))
        updated = remove_blocks(state, [('media',0)], self.media)
        self.assertEqual(updated.edits.media_clips,(second,))
        self.assertEqual(state.edits.media_clips,(first,second))
        self.assertEqual(self.photo.read_bytes(),b'untouched-image')
        self.assertEqual(self.source.read_bytes(),b'original-data')

    def test_remove_one_emoji_keeps_other(self):
        first = VisualCue('emoji','emoji.skull',2.,4.)
        second = VisualCue('emoji','emoji.laugh',5.,9.)
        state = self.state(overlays=(first,second))
        updated = remove_blocks(state,[('overlay',0)],self.media)
        self.assertEqual(updated.edits.overlays,(second,))
        self.assertEqual(len(state.edits.overlays),2)

    def test_delete_one_sound_preserves_other_audio(self):
        first = SoundCue('silence.pause',2.,duration=.5)
        second = SoundCue('silence.pause',4.,duration=.5)
        state = self.state(sounds=(first,second))
        updated = remove_blocks(state,[('sound',1)],self.media)
        self.assertEqual(updated.edits.sounds,(first,))
        self.assertEqual(state.edits.sounds,(first,second))

    def test_delete_timed_caption_not_global_text(self):
        a,b = Caption(1.,3.,'One'),Caption(4.,6.,'Two')
        state = self.state(text=TextOverlay(True,'TITLE',captions=(a,b)))
        updated=remove_blocks(state,[('caption',0)],self.media)
        self.assertEqual(updated.edits.text.captions,(b,))
        self.assertEqual(updated.edits.text.text,'TITLE')
        self.assertTrue(updated.edits.text.enabled)

    def test_delete_music_disables_without_losing_track_selection(self):
        state=self.state(music=Music(enabled=True,track='Pulse // Drive',music_volume=.3))
        updated=remove_blocks(state,[('music',0)],self.media)
        self.assertFalse(updated.edits.music.enabled)
        self.assertEqual(updated.edits.music.track,'Pulse // Drive')
        self.assertAlmostEqual(updated.edits.music.music_volume,.3)

    def test_delete_crop_keyframe_preserves_remaining_keyframes(self):
        base=EditOptions().with_format(self.media,SHORTS_FORMAT)
        x,y=base.crop.x,base.crop.y
        keys=(CropKeyframe(2.,x,y),CropKeyframe(10.,x,y))
        state=EditSnapshot(self.trim,CutPlan(),replace(base,crop_motion=CropMotion(keys)))
        updated=remove_blocks(state,[('crop_key',0)],self.media)
        self.assertEqual(updated.edits.crop_motion.keyframes,(keys[1],))
        self.assertEqual(state.edits.crop_motion.keyframes,keys)

    def test_delete_zoom_disables_effect(self):
        state=self.state(zoom=Zoom(enabled=True))
        updated=remove_blocks(state,[('zoom',0)],self.media)
        self.assertFalse(updated.edits.zoom.enabled)

    def test_delete_multiple_overlays_and_keep_nonselected(self):
        cues=tuple(MediaClip(str(self.photo),'photo',float(i),float(i+1))
                   for i in (1,3,5))
        state=self.state(media_clips=cues)
        updated=remove_blocks(state,[('media',0),('media',2)],self.media)
        self.assertEqual(updated.edits.media_clips,(cues[1],))

    def test_cannot_delete_original_video_or_stale_index(self):
        state=self.state()
        for key in (('video',0),('scene',0),('media',0),('overlay',0),
                    ('sound',0),('music',0),('zoom',0),('crop_key',0)):
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'editable'):
                remove_blocks(state,[key],self.media)

    def test_history_reinstates_removed_item_then_redoes(self):
        cue=MediaClip(str(self.photo),'photo',1.,4.)
        before=self.state(media_clips=(cue,))
        history=EditHistory(before)
        after=remove_blocks(before,[('media',0)],self.media)
        self.assertTrue(history.record(after))
        self.assertEqual(history.undo(),before)
        self.assertEqual(history.redo(),after)

    def test_timeline_key_tracks_actual_edit_index(self):
        a,b=MediaClip(str(self.photo),'photo',1.,3.),MediaClip(str(self.photo),'photo',4.,6.)
        state=self.state(media_clips=(a,b))
        keys=[block.key for block in blocks(state) if block.kind=='media']
        self.assertEqual(keys,[('media',0),('media',1)])
        updated=remove_blocks(state,[keys[0]],self.media)
        keys=[block.key for block in blocks(updated) if block.kind=='media']
        self.assertEqual(keys,[('media',0)])


if __name__=='__main__':
    unittest.main()
