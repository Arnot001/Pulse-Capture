"""Windows Tk checks for Commentary Studio without real microphone or OpenVoice model."""
import os
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import wave

from editor.commentary_ui import CommentaryStudio
from editor.voice_assets import new_path
from tests.test_quick_edit_workspace_ui import QuickEditWorkspaceUITests


def wav(path,secs=2):
    with wave.open(str(path),'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(48000)
        out.writeframes(b'\x08\x00'*int(48000*secs))


@unittest.skipUnless(os.name=='nt' and os.environ.get('PULSE_RUN_UI_TESTS')=='1',
                     'Windows GUI opt-in only')
class CommentaryUITests(unittest.TestCase):
    setUp=QuickEditWorkspaceUITests.setUp
    close_window=QuickEditWorkspaceUITests.close_window
    pump_until=QuickEditWorkspaceUITests.pump_until

    def make_studio(self):
        self.window.open_commentary_studio()
        self.root.update()
        studio=self.window.commentary_studio
        self.assertIsNotNone(studio)
        self.assertTrue(studio.winfo_exists())
        return studio

    def make_take(self,studio):
        path=new_path('recording')
        wav(path)
        studio._recording_playhead=1.
        studio._video_started=True
        studio.recorder.started_at=time.monotonic()-1
        self.window.play_started=studio.recorder.started_at+.3
        studio._record_saved(path)
        self.root.update()
        return path

    def test_add_menu_opens_studio_without_starting_microphone(self):
        w=self.window
        menu=w.add_menu.nametowidget(w.add_menu.cget('menu'))
        labels=[menu.entrycget(i,'label') for i in range(menu.index('end')+1)]
        self.assertIn('🎙 Record Commentary',labels)
        studio=self.make_studio()
        self.assertFalse(studio.recorder.active)
        self.assertEqual(len(w.edits.commentary_clips),0)
        self.assertGreater(studio.wave.winfo_width(),100)

    def test_recording_floats_stop_controls_and_leaves_video_visible(self):
        studio=self.make_studio()
        studio.devices=[dict(index=0,name='Test microphone')]
        studio.device_picker.configure(values=('Test microphone',))
        studio.device_picker.current(0)
        with patch.object(studio.recorder,'start') as start:
            studio.record()
            self.root.update()
            start.assert_called_once_with(0)
            self.assertTrue(studio._hud.winfo_ismapped())
            self.assertFalse(studio.winfo_ismapped())
            self.assertGreater(self.window.video.winfo_width(),250)
            studio._hide_recording_hud()
            self.root.update()
            self.assertTrue(studio.winfo_ismapped())

    def test_record_take_edit_split_undo_and_revert_audio(self):
        studio=self.make_studio()
        with patch.dict(os.environ,{'LOCALAPPDATA':self.temp.name}):
            original=self.make_take(studio)
            self.assertTrue(original.is_file())
            self.assertEqual(len(self.window.edits.commentary_clips),1)
            c=self.window.edits.commentary_clips[0]
            self.assertEqual(c.original_file,str(original))
            self.assertEqual(c.file,str(original))
            self.assertEqual([b.kind for b in self.window.timeline.clip_blocks
                              if b.track==5],['commentary'])
            studio.volume_var.set('.8')
            studio.background_var.set('.25')
            studio.apply()
            self.assertAlmostEqual(self.window.edits.commentary_clips[0].volume,.8)
            self.window.position=1.5
            studio.split()
            self.assertEqual(len(self.window.edits.commentary_clips),2)
            self.assertAlmostEqual(self.window.edits.commentary_clips[1].source_in,.8,delta=.01)
            studio.remove()
            self.assertEqual(len(self.window.edits.commentary_clips),1)
            self.window.undo_timeline()
            self.assertEqual(len(self.window.edits.commentary_clips),2)
            self.assertTrue(original.is_file())

    def test_converted_voice_is_switchable_back_to_original(self):
        studio=self.make_studio()
        with patch.dict(os.environ,{'LOCALAPPDATA':self.temp.name}):
            original=self.make_take(studio)
            changed=new_path('converted')
            wav(changed,2)
            with patch.object(studio,'_selected_voice',
                return_value=SimpleNamespace(model='mock-model',id='en-br')):
                with patch('editor.commentary_ui.convert_voice',return_value=changed):
                    studio.convert()
                    self.pump_until(lambda: not studio._busy)
            self.assertEqual(Path(self.window.edits.commentary_clips[0].file).resolve(),changed.resolve())
            studio.use_original()
            self.assertEqual(Path(self.window.edits.commentary_clips[0].file).resolve(),original.resolve())
            self.assertTrue(changed.is_file())
            self.assertTrue(original.is_file())

    def test_export_refuses_active_microphone_capture(self):
        studio=self.make_studio()
        with patch.object(type(studio.recorder),'active',new_callable=lambda:property(lambda _rec:True)):
            self.window.export()
            self.assertIn('Stop and save commentary',self.window.note.cget('text'))
            self.assertFalse(self.window.exporter.busy)


if __name__=='__main__':
    unittest.main()
