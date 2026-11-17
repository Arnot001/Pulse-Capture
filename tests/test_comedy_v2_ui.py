"""Exercise real Tk controls, cue persistence, preview and export on Windows."""
from dataclasses import replace
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from tests import test_pulse_plan_ui as fixture
from editor.reaction_tools import ReactionDialog
from editor.caption_tools import CaptionDialog
from editor.pulse_plan import starter_plan, source_identity


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS')=='1','Opt-in Windows Tk integration')
class ComedyUITests(unittest.TestCase):
    setUp=fixture.PulsePlanUITests.setUp
    cleanup=fixture.PulsePlanUITests.cleanup
    pump=fixture.PulsePlanUITests.pump

    def test_sound_emoji_caption_persistence_and_export(self):
        with patch.dict(os.environ,PULSE_REACTION_LIBRARY=str(self.folder/'library')):
            w=self.window
            w.open_reactions('sfx')
            sound=next(c for c in w.auto_children if isinstance(c,ReactionDialog))
            sound.assets.selection_set('comedy.boing');sound.values['at'].set('1')
            sound.values['duck_source'].set('.35');sound.save(False)
            self.assertEqual(len(w.edits.sounds),1,sound.note.cget('text'))
            self.assertTrue(w.timeline.find_withtag('reaction-cue'))
            sound.cues.selection_set(0);sound.select_cue();sound.values['at'].set('1.2');sound.save(True)
            self.assertEqual(w.edits.sounds[0].at,1.2)
            path=self.folder/'cues.json'
            with patch('editor.reaction_tools.filedialog.asksaveasfilename',return_value=str(path)):sound.save_cues()
            sound.cues.selection_set(0);sound.remove();self.assertEqual(w.edits.sounds,())
            with patch('editor.reaction_tools.filedialog.askopenfilename',return_value=str(path)):sound.load_cues()
            self.assertEqual(len(w.edits.sounds),1,sound.note.cget('text'));sound.close()
            w.open_reactions('emoji')
            emoji=next(c for c in w.auto_children if isinstance(c,ReactionDialog))
            emoji.assets.selection_set('emoji.skull');emoji.values['start'].set('1');emoji.values['end'].set('2.5');emoji.save(False)
            self.assertEqual(len(w.edits.overlays),1,emoji.note.cget('text'));emoji.close()
            captions=CaptionDialog(w);captions.start.set('1');captions.end.set('2.5')
            captions.input.insert('1.0','THAT WAS PERSONAL');captions.style_vars['highlight'].set('PERSONAL');captions.save(False)
            self.assertEqual(w.edits.text.captions[-1].style.font_size,88,captions.note.cget('text'));captions.destroy()
            old=w.video.photo;w.seek(1.4);self.pump(lambda:w.video.photo is not old)
            w.update_trim(replace(w.trim,end=min(3,w.media.duration)))
            w.output_folder=self.folder;w.export()
            self.pump(lambda:w.last_export is not None or not w.exporter.busy)
            self.assertIsNotNone(w.last_export,w.note.cget('text'))

    def test_effect_picker_updates_recipe_and_undo(self):
        w=self.window
        w.open_reactions('effects')
        dialog=next(iter(w.auto_children));self.pump(lambda:not dialog.busy)
        plan=starter_plan(w.media,source_identity(w.media,threading.Event()))
        plan['timeline']=[dict(kind='shot',start=0,end=1),dict(kind='shot',start=1,end=2)]
        dialog.set_plan(plan)
        picker=dialog.effect_picker;picker.index.set('1');picker.apply('Freeze-frame')
        self.assertEqual(dialog.get_plan()['timeline'][1]['duration'],1.8)
        picker.apply('Undo');self.assertEqual(dialog.get_plan(),plan)
        picker.apply('Quick shake');self.assertEqual(dialog.get_plan()['timeline'][0]['effect'],'shake')
        picker.apply('Remove visual effect');self.assertNotIn('effect',dialog.get_plan()['timeline'][0])
        dialog.close()


if __name__=='__main__':unittest.main()
