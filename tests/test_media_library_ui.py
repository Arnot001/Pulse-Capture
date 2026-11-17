from dataclasses import replace
import gc
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from capture.ffmpeg_backend import run
from editor.reaction_library import ReactionLibrary, bundled_gifs
from editor.reaction_tools import ReactionDialog
from editor.music_details import MusicDetails
from editor.music import IMPORT_LABEL
from editor.music_library import MusicLibrary, YOUTUBE_LIBRARY_URL
from tests import test_pulse_plan_ui as fixture


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS')=='1','Opt-in Windows Tk integration')
class MediaLibraryUITests(unittest.TestCase):
    pump=fixture.PulsePlanUITests.pump

    def cleanup(self):
        fixture.PulsePlanUITests.cleanup(self)
        # Collect destroyed Tk variable cycles on their owning thread before a
        # later test's media worker can trigger Python's automatic collector.
        self.window=self.root=None
        gc.collect()

    def setUp(self):
        gc.collect()
        fixture.PulsePlanUITests.setUp(self)
        self.env=patch.dict(os.environ,PULSE_REACTION_LIBRARY=str(self.folder/'reactions'),PULSE_MUSIC_CACHE=str(self.folder/'music'))
        self.env.start();self.addCleanup(self.env.stop)

    def test_gif_library_lazy_thumbnails_animation_and_multifile_import(self):
        dialog=ReactionDialog(self.window,'gif');self.root.update()
        self.assertEqual(len(dialog.assets.get_children()),64)
        self.pump(lambda:bool(dialog.images))
        self.assertLess(len(dialog.images),len(bundled_gifs()))
        dialog.assets.selection_set('reaction.facepalm');dialog.preview_asset()
        first=dialog.preview_photo
        self.pump(lambda:dialog.preview_photo is not first)
        dialog.stop_preview();self.assertIsNone(dialog.preview_timer)
        dialog.search.set('cry');self.assertTrue(dialog.assets.get_children())
        dialog.search.set('');self.root.update()
        dialog.assets.selection_set(('reaction.cry','reaction.facepalm'))
        with patch('editor.reaction_tools.simpledialog.askstring',return_value='My reactions'):dialog.categorize()
        dialog.category.set('My reactions');self.root.update()
        self.assertEqual(set(dialog.assets.get_children()),{'reaction.cry','reaction.facepalm'})
        path=ReactionLibrary().resolve('reaction.laugh')
        bad=self.folder/'broken.gif';bad.write_bytes(b'invalid')
        with patch('editor.reaction_tools.filedialog.askopenfilenames',return_value=(str(path),str(path),str(bad))):dialog.import_asset()
        self.pump(lambda:not dialog.busy)
        self.assertIn('duplicates 2',dialog.note.cget('text'));self.assertIn('failed 1',dialog.note.cget('text'))
        self.assertEqual(len(dialog.assets.get_children()),64)

    def test_sound_preview_never_blocks_tk_and_close_cancels(self):
        dialog=ReactionDialog(self.window,'sfx')
        self.assertGreaterEqual(len(dialog.assets.get_children()),150)
        ready=threading.Event();release=threading.Event()
        path=self.folder/'test.wav'
        result=run([self.window.backend.ffmpeg,'-v','error','-f','lavfi','-i','sine=d=0.2',str(path)],20)
        self.assertEqual(result.returncode,0,result.stderr)
        def slow_resolve(*_):ready.set();release.wait(3);return path
        with patch.object(dialog.library,'resolve',side_effect=slow_resolve):
            dialog.assets.selection_set('original.rimshot')
            started=time.monotonic();dialog.preview_asset()
            self.assertLess(time.monotonic()-started,.3)
            self.pump(ready.is_set)
            flag=[];self.root.after(30,lambda:flag.append(True));self.pump(lambda:flag)
            worker=dialog.audition.worker;dialog.close();release.set()
            self.pump(lambda:not worker.is_alive())
        self.assertTrue(dialog.closed)

    def test_youtube_browser_music_credit_persistence_trim_and_preview(self):
        w=self.window;tools=w.music_tools
        with patch('webbrowser.open') as opened:
            tools.browse_youtube();opened.assert_called_once_with(YOUTUBE_LIBRARY_URL)
        source=self.folder/'downloaded.mp3'
        made=run([w.backend.ffmpeg,'-v','error','-f','lavfi','-i','sine=frequency=700:duration=2','-c:a','libmp3lame',str(source)],20)
        self.assertEqual(made.returncode,0,made.stderr)
        with patch('editor.music_tools.filedialog.askopenfilename',return_value=str(source)):tools.import_audio()
        tools.open_library();dialog=next(c for c in w.auto_children if isinstance(c,MusicDetails))
        self.assertEqual(dialog.licence.get(),'Unspecified — verify rights')
        dialog.values['name'].set('Fixture track');dialog.values['artist'].set('Fixture artist')
        dialog.values['source'].set('YouTube Audio Library')
        dialog.licence.set('Creative Commons Attribution');dialog.required.set(True)
        credit='Fixture by Fixture artist\nCredit text copied from the provider'
        dialog.credit.insert('1.0',credit);dialog.copy_credit()
        self.assertEqual(self.root.clipboard_get(),credit)
        dialog.start.set('.2');dialog.end.set('1.2');dialog.duck.set(True)
        dialog.save();self.pump(lambda:not dialog.busy)
        self.assertEqual(len(MusicLibrary().items()),1,dialog.note.cget('text'))
        self.assertNotEqual(w.edits.music.imported,source)
        self.assertEqual(Path(w.edits.music.imported).read_bytes(),source.read_bytes())
        self.assertEqual(w.edits.music.trim_start,.2);self.assertTrue(w.edits.music.duck_dialogue)
        with patch('winsound.PlaySound') as play:
            dialog.preview();self.pump(lambda:'Playing preview' in dialog.note.cget('text'))
            self.assertTrue(play.called)
        dialog.close();tools.open_library()
        reopened=next(c for c in w.auto_children if isinstance(c,MusicDetails))
        self.assertEqual(reopened.credit.get('1.0','end-1c'),credit)
        w.exporter.busy=True
        try:
            before=w.edits;reopened.start.set('.4');self.assertFalse(reopened.apply());self.assertEqual(w.edits,before)
        finally:w.exporter.busy=False


if __name__=='__main__':unittest.main()
