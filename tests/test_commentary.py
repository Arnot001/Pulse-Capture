"""Offline, non-destructive commentary track and FFmpeg graph regression tests."""
from dataclasses import replace
from pathlib import Path
import math
import os
import tempfile
import unittest
import wave

from editor.commentary_effects import EFFECTS, voice_effect_filters, validate_effect
from editor.commentary import (
    CommentaryClip, adjust_timing, add_commentary, split_clip, validate_commentary)
from editor.cuts import CutPlan
from editor.edit_history import EditHistory, EditSnapshot
from editor.models import MediaInfo, TrimRange
from editor.timeline_edits import blocks, change_timing, remove_blocks
from editor.transforms import EditOptions
from editor.audio_preview import audio_preview_command


def make_wav(path, seconds=3, rate=48000):
    with wave.open(str(path), 'wb') as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(b'\x00\x00' * int(seconds * rate))


class CommentaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.old = os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA'] = self.temp.name
        self.addCleanup(self.restore)
        self.library = Path(self.temp.name) / 'Pulse Capture' / 'voiceovers'
        self.library.mkdir(parents=True, exist_ok=True)
        self.raw = self.library / 'recording-original.wav'
        self.fx = self.library / 'converted-voice.wav'
        make_wav(self.raw, 3.)
        make_wav(self.fx, 2.4)
        self.source = Path(self.temp.name) / 'source.mp4'
        self.source.write_bytes(b'safe')
        self.media = MediaInfo(self.source, 8., 640, 360, 30., False)

    def restore(self):
        if self.old is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = self.old

    def clip(self, **kw):
        return replace(CommentaryClip(str(self.raw), 1., 3., original_file=str(self.raw)), **kw)

    def state(self, *cues):
        return EditSnapshot(TrimRange(0.,8.), CutPlan(),
                            EditOptions(commentary_clips=tuple(cues)))

    def test_validates_library_and_source_boundaries(self):
        self.clip().validate(8.)
        for fields in (dict(start=-1), dict(end=9), dict(source_in=2),
                       dict(volume=3), dict(background_gain=-1),
                       dict(fade_in=-.1), dict(start=float('nan'))):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.clip(**fields).validate(8.)
        elsewhere = Path(self.temp.name) / 'elsewhere.wav'
        make_wav(elsewhere)
        with self.assertRaisesRegex(ValueError,'saved Pulse'):
            self.clip(file=str(elsewhere)).validate(8.)

    def test_split_keeps_source_alignment_and_original_untouched(self):
        original = self.raw.read_bytes()
        before = self.clip(source_in=.2, end=3.1)
        left, right = split_clip(before,2.25)
        self.assertAlmostEqual(left.end,2.25)
        self.assertAlmostEqual(right.source_in,1.45)
        self.assertAlmostEqual(right.duration,.85)
        self.assertEqual(left.file,right.file)
        self.assertEqual(self.raw.read_bytes(),original)

    def test_move_and_left_edge_trim_do_not_shift_wrong_audio(self):
        clip=self.clip()
        moved=adjust_timing(clip,3.,5.)
        self.assertEqual(moved.source_in,0)
        shorter=adjust_timing(clip,1.6,3.)
        self.assertAlmostEqual(shorter.source_in,.6)
        self.assertEqual(shorter.end,3.)
        edge=adjust_timing(clip,1.,2.2)
        self.assertEqual(edge.source_in,0)
        with self.assertRaises(ValueError):
            adjust_timing(clip,1.,4.5)

    def test_converted_voice_reversible_without_replacing_original(self):
        original = self.clip()
        changed = original.with_file(self.fx)
        self.assertEqual(changed.original_file,str(self.raw))
        self.assertEqual(Path(changed.file).resolve(),self.fx.resolve())
        self.assertAlmostEqual(changed.duration,2.)
        restored=changed.with_file(self.raw)
        self.assertEqual(Path(restored.file).resolve(),self.raw.resolve())
        self.assertEqual(self.raw.stat().st_size,288044)

    def test_overlapping_ducking_and_preview_offset_graph(self):
        cue = self.clip(start=1,end=3,volume=.8,background_gain=.3)
        inputs=['-i','original.mp4']
        graph=[]
        label=add_commentary(inputs,graph,'source',(cue,),duration=1,offset=1.5)
        self.assertEqual(label,'commentarymix')
        text=';'.join(graph)
        self.assertIn('atrim=start=0.500000000:duration=1.000000000',text)
        self.assertIn("volume='min(1,if(between(t,0.000000000,1.000000000),0.3,1))'",text)
        self.assertIn('amix=inputs=2',text)
        self.assertEqual(inputs.count('-i'),2)
        self.assertEqual(add_commentary(inputs,graph,'source',(cue,),1,offset=4),'source')

    def test_auto_duck_off_keeps_background_gain_unmodified(self):
        cue=self.clip(background_gain=.15,auto_duck=False)
        graph=[]
        inputs=['-i','source.mp4']
        self.assertEqual(
            add_commentary(inputs,graph,'source',(cue,),duration=3),
            'commentarymix')
        self.assertIn('amix=inputs=2',';'.join(graph))
        self.assertNotIn('between(t,',';'.join(graph))
        self.assertNotIn('0.15,1)', ';'.join(graph))
        with self.assertRaises(ValueError):
            self.clip(auto_duck='False').validate(8.)

    def test_voice_effects_are_validated_and_added_to_only_selected_takes(self):
        self.assertEqual(EFFECTS, ('None','Echo','Reverb','Chorus'))
        self.assertEqual(voice_effect_filters('None', .6), [])
        self.assertEqual(voice_effect_filters('Reverb', 0.), [])
        for effect, marker in (('Echo','aecho='),('Reverb','aecho='),('Chorus','chorus=')):
            with self.subTest(effect=effect):
                cue=self.clip(effect=effect,effect_strength=.6)
                cue.validate(8.)
                inputs=['-i','video.mp4']
                graph=[]
                self.assertEqual(add_commentary(inputs,graph,'source',(cue,),3),
                                 'commentarymix')
                self.assertIn(marker, ';'.join(graph))
                self.assertIn('atrim=duration=2.000000000', ';'.join(graph))
                self.assertEqual(inputs.count('-i'),2)
        for effect,amount in (('Other',.5),('Echo',-1),('Chorus',1.01),
                              ('Reverb',float('nan')),('Echo',True)):
            with self.subTest(effect=effect,amount=amount):
                with self.assertRaises(ValueError):
                    validate_effect(effect,amount)

    def test_effect_preserved_across_split_and_non_destructive_reversion(self):
        cue=self.clip(effect='Chorus',effect_strength=.8)
        left,right=split_clip(cue,2.)
        self.assertEqual((left.effect,right.effect),('Chorus','Chorus'))
        self.assertEqual((left.effect_strength,right.effect_strength),(.8,.8))
        with self.assertRaises(ValueError):
            self.clip(effect='invalid').validate(8.)
        converted=cue.with_file(self.fx)
        self.assertEqual(converted.effect,'Chorus')
        self.assertEqual(converted.with_file(self.raw).effect,'Chorus')
        self.assertTrue(self.raw.is_file())

    def test_no_original_audio_bed_still_supports_voice(self):
        clip=self.clip()
        state=self.state(clip)
        command=audio_preview_command('ffmpeg',self.media,0.,state.trim,state.cuts,state.edits)
        self.assertIn('-filter_complex',command)
        graph=command[command.index('-filter_complex')+1]
        self.assertIn('anullsrc=r=48000',graph)
        self.assertIn('commentarymix',graph)
        self.assertIn(str(self.raw.resolve()),command)

    def test_one_voice_block_drag_trim_delete_and_history(self):
        clip=self.clip()
        state=self.state(clip)
        voice=[b for b in blocks(state) if b.kind=='commentary']
        self.assertEqual(len(voice),1)
        self.assertEqual((voice[0].track,voice[0].key),(5,('commentary',0)))
        moved=change_timing(state,voice[0].key,2.,4.,self.media)
        self.assertEqual(moved.edits.commentary_clips[0].start,2.)
        trimmed=change_timing(state,voice[0].key,1.5,3.,self.media)
        self.assertAlmostEqual(trimmed.edits.commentary_clips[0].source_in,.5)
        empty=remove_blocks(moved,[voice[0].key],self.media)
        self.assertEqual(empty.edits.commentary_clips,())
        h=EditHistory(state)
        self.assertTrue(h.record(empty))
        self.assertEqual(h.undo(),state)
        self.assertEqual(h.redo(),empty)

    def test_limit_and_stale_delete_protected(self):
        with self.assertRaisesRegex(ValueError,'at most 24'):
            validate_commentary((self.clip(),)*25,8.)
        with self.assertRaises(ValueError):
            remove_blocks(self.state(),[('commentary',0)],self.media)
        with self.assertRaises(ValueError):
            remove_blocks(self.state(),[('video',0)],self.media)


if __name__ == '__main__':
    unittest.main()
