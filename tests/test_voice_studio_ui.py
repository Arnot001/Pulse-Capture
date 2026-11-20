"""Windows Tk Voice Studio import, controls, placement and reuse; no paid requests."""
from dataclasses import replace
import os
from pathlib import Path
import shutil
import threading
import time
import unittest
from unittest.mock import patch

from editor.ai_voiceover_ui import VoiceoverStudio
from editor.voice_assets import import_audio
from editor.voice_catalogue import Voice
from tests import test_pulse_plan_ui as fixture
from tests.test_voice_studio_v2 import tone


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS') == '1', 'Opt-in Windows Tk integration')
class VoiceStudioUITests(unittest.TestCase):
    setUp = fixture.PulsePlanUITests.setUp
    cleanup = fixture.PulsePlanUITests.cleanup
    pump = fixture.PulsePlanUITests.pump

    def test_import_place_move_replace_and_reopen(self):
        with patch.dict(os.environ, {'LOCALAPPDATA':str(self.folder)}):
            source = self.folder/'my-take.wav'
            tone(source)
            self.window.position = 3
            self.window.edits = replace(self.window.edits, speed=1.5)
            studio = VoiceoverStudio(self.window)
            try:
                panel = studio.change_voice
                self.pump(lambda: not panel.busy)
                self.assertAlmostEqual(panel.start.get(), 2)
                with patch('editor.voice_studio_panel.filedialog.askopenfilename', return_value=str(source)):
                    panel.import_recording()
                self.pump(lambda: panel.original is not None)
                original = panel.original
                panel.values['pitch'].set(4)
                panel.values['speed'].set(1.5)
                panel.preview_settings()
                self.pump(lambda: not panel.busy)
                self.assertNotEqual(panel.output, original)
                self.assertTrue(original.is_file())
                panel.attach()
                self.assertAlmostEqual(self.window.edits.narration.start, 2)
                panel.start.set(.5)
                panel.track_volume.set(.7)
                panel.duck.set(.2)
                panel.attach()
                self.assertEqual(self.window.edits.narration.start, .5)
                self.assertEqual(self.window.edits.narration.volume, .7)
                self.assertEqual(self.window.edits.narration.background_gain, .2)
                studio.close()
                studio = VoiceoverStudio(self.window)
                panel = studio.change_voice
                self.assertEqual(panel.start.get(), .5)
                self.assertEqual(panel.output, Path(self.window.edits.narration.file))
                self.pump(lambda: not panel.busy)
                panel.remove()
                self.assertIsNone(self.window.edits.narration)
                self.assertTrue(original.exists())
                self.assertFalse(self.errors)
            finally:
                studio.close()

    def test_paid_generation_requires_confirmation_and_key_is_masked(self):
        with patch.dict(os.environ, {'LOCALAPPDATA':str(self.folder)}):
            studio = VoiceoverStudio(self.window)
            try:
                studio.script.insert('1.0', 'No request without confirmation.')
                with patch('editor.ai_voiceover_ui.messagebox.askyesno', return_value=False), \
                     patch('editor.ai_voiceover_ui.generate') as generate:
                    studio.make_button.invoke()
                    generate.assert_not_called()
                self.assertTrue(studio.key_entry.cget('show'))
                self.assertEqual(len(studio.tabs.tabs()), 2)
            finally:
                studio.close()

    def test_credit_counter_reconciles_and_flags_unknown_charge(self):
        with patch.dict(os.environ, {'LOCALAPPDATA':str(self.folder)}):
            studio = VoiceoverStudio(self.window)
            try:
                panel = studio.credit_panel
                self.pump(lambda: not panel.pending)
                with patch('editor.api_credits_ui.simpledialog.askfloat', return_value=20.):
                    panel.set_balance()
                self.pump(lambda: not panel.pending)
                self.assertIn('$20.0000', panel.label.cget('text'))
                voices = self.folder/'Pulse Capture/voiceovers'
                voices.mkdir(parents=True, exist_ok=True)
                (voices/'offline-test.attempt').write_text('Test fixture, no API request')
                panel.refresh()
                self.pump(lambda: not panel.pending)
                self.assertIn('billing check needed', panel.label.cget('text'))
                self.assertLessEqual(panel.winfo_y()+panel.winfo_height(), studio.winfo_height())
            finally:
                studio.close()

    def test_reference_dialog_requires_permission_and_selects_added_voice(self):
        with patch.dict(os.environ, {'LOCALAPPDATA':str(self.folder)}):
            source = self.folder/'reference.wav'
            tone(source, seconds=4)
            studio = VoiceoverStudio(self.window)
            try:
                panel = studio.change_voice
                self.pump(lambda: not panel.busy)
                with patch('editor.voice_studio_panel.filedialog.askopenfilename', return_value=str(source)):
                    panel.add_reference()
                dialog = panel.reference_dialog
                self.pump(lambda: not dialog.busy)
                self.assertIsNotNone(dialog.reference)
                self.assertIn('4.00 seconds', dialog.info.cget('text'))
                temporary = dialog.reference.wav.parent
                with patch.object(panel.catalogue, 'add_reference') as add:
                    dialog.create()
                    add.assert_not_called()
                dialog.values['name'].set('Local test voice')
                dialog.values['permission'].set('own voice')
                dialog.values['provenance'].set('Generated test fixture, no person')
                dialog.consent.set(True)
                from dataclasses import asdict
                def add(reference, labels, cancel):
                    voice = Voice('test-ref', labels['name'], 'missing.pth', metadata_origin='User-provided')
                    panel.catalogue.state['custom'].append(asdict(voice))
                    return voice
                with patch.object(panel.catalogue, 'add_reference', side_effect=add):
                    dialog.create()
                    self.pump(lambda: panel.reference_dialog is None)
                self.assertEqual(panel.selected().id, 'test-ref')
                self.assertFalse(temporary.exists())
                self.assertFalse(self.errors)
            finally:
                studio.close()

    def test_closing_studio_cancels_reference_work_and_removes_temporary_audio(self):
        with patch.dict(os.environ, {'LOCALAPPDATA':str(self.folder)}):
            source = self.folder/'reference-cancel.wav'
            tone(source, seconds=4)
            studio = VoiceoverStudio(self.window)
            panel = studio.change_voice
            self.pump(lambda: not panel.busy)
            with patch('editor.voice_studio_panel.filedialog.askopenfilename', return_value=str(source)):
                panel.add_reference()
            dialog = panel.reference_dialog
            self.pump(lambda: not dialog.busy)
            temporary = dialog.reference.wav.parent
            dialog.values['name'].set('Cancellation test')
            dialog.values['permission'].set('own voice')
            dialog.values['provenance'].set('Generated test fixture')
            dialog.consent.set(True)
            started = threading.Event()
            def work(reference, labels, cancel):
                started.set()
                if not cancel.wait(5):
                    raise RuntimeError('Cancel signal was not delivered')
                raise ValueError('Cancelled')
            with patch.object(panel.catalogue, 'add_reference', side_effect=work):
                dialog.create()
                self.pump(started.is_set)
                studio.close()
                self.pump(lambda: not temporary.exists())
            self.assertTrue(source.exists())
            self.assertFalse(self.errors)


if __name__ == '__main__':
    unittest.main()
