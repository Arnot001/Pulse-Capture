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
            self.pump(lambda:w.last_export is not None)
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

    def test_comedy_toggle_band_caption_zone_and_full_audio_default(self):
        with patch.dict(os.environ,PULSE_REACTION_LIBRARY=str(self.folder/'library')):
            w=self.window
            w.select_tool('FORMAT');w.comedy_on.set(True);w.comedy_changed()
            self.assertEqual(w.edits.comedy_bands,(w.media.width,w.media.height),w.note.cget('text'))
            captions=CaptionDialog(w)
            captions.input.insert('1.0','DOGGO COMES FIRST')
            captions.save(False)
            self.assertEqual(w.edits.text.captions[0].style.font_size,104,captions.note.cget('text'))
            captions.destroy()
            w.open_reactions('emoji')
            dialog=next(c for c in w.auto_children if isinstance(c,ReactionDialog))
            self.assertEqual(dialog.zone.get(),'bottom')
            dialog.assets.selection_set('emoji.skull');dialog.save(False)
            self.assertEqual(w.edits.overlays[0].zone,'bottom',dialog.note.cget('text'))
            w.comedy_on.set(False);w.comedy_changed()
            self.assertTrue(w.comedy_on.get())  # Cannot silently strand a band overlay.
            dialog.close()
            w.open_reactions('sfx')
            sound=next(c for c in w.auto_children if isinstance(c,ReactionDialog))
            self.assertEqual(sound.values['duration'].get(),'')
            self.assertIn('WTF',sound.categories.cget('values'))
            self.pump(lambda:sound.assets.winfo_height()>1)
            self.assertGreater(sound.assets.winfo_height(),100)
            self.assertLess(sound.note.winfo_y()+sound.note.winfo_height(),sound.winfo_height()+1)
            sound.close()

    def test_saved_ai_recovery_is_visible_without_request(self):
        from types import SimpleNamespace
        from editor.auto_tools import AutoEditDialog
        from unittest.mock import Mock
        dialog=AutoEditDialog(self.window)
        self.addCleanup(dialog.finish_close)
        folder=self.folder/'saved-job';folder.mkdir()
        (folder/'ai-response.json').write_text('{}',encoding='utf-8')
        dialog.job=SimpleNamespace(folder=folder,request={'model':'test'},analysis={'duration':6},
            quote={'estimated_gbp':.01,'reserved_upper_gbp':.1},transcript_note='Offline fixture',ai=Mock())
        dialog.events.put(('prepared',None));dialog.poll()
        self.assertEqual(dialog.ai_button.cget('text'),'REUSE SAVED AI')
        with patch.object(dialog,'work') as work:
            dialog.ai()
            self.assertIn('No new paid request',dialog.status.cget('text'))
            work.assert_called_once()
        dialog.job.ai.assert_not_called()
        dialog.close()


if __name__=='__main__':unittest.main()
