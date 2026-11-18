"""Phrase search, persistent metadata and the real Windows soundboard workflow."""
from array import array
from dataclasses import replace
import gc
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from capture.ffmpeg_backend import run
from editor.reaction_library import ReactionLibrary
from editor.reaction_tools import ReactionDialog
from editor.reaction_details import ReactionDetails
from editor.soundboard import matches, in_category, rights_label, discovery_url
from editor.reaction_suggestions import suggest, caption_context, is_voice
from editor.text_overlay import Caption
from editor.cuts import CutPlan, CutRange
from editor.models import TrimRange
from editor.reactions import SoundCue
from editor.transforms import EditOptions
from editor.audio_preview import audio_preview_command
from editor.ffmpeg_export import build_export_command
from tests import test_pulse_plan_ui as fixture
from tests import test_media_library_integration as render_fixture


class SoundboardTests(unittest.TestCase):
    def test_suggestions_use_existing_distinct_recordings_outside_speech(self):
        class Library:
            def items(self,kind):return [
                dict(id='import.a',kind='sfx',name='OH HELL NAH',duration=.6,category='Imported'),
                dict(id='import.b',kind='sfx',name='BRUH',duration=.6,category='Imported'),
                dict(id='import.voice',kind='sfx',name='NO WAY',duration=.6,category='Disbelief',audio_type='windows_voice'),
                dict(id='original.nope',kind='sfx',name='Nope',duration=.6,category='Disbelief')]
            def resolve(self,key,kind):return Path(key)
            def metadata(self,key,kind):return next(i for i in self.items(kind) if i['id']==key)
        library=Library();captions=[dict(start=a,end=a+1,text='No way!') for a in (1,5,9)]
        found=suggest(library,captions,[(0,1.5)],12)
        self.assertEqual(len(found),2)
        self.assertEqual({c.asset_id for c,_ in found},{'import.a','import.b'})
        self.assertGreaterEqual(found[0][0].at,1.65)
        self.assertEqual(suggest(library,captions,[(0,12)],12),[])
        self.assertEqual(suggest(library,captions,[],12,existing=tuple(c for c,_ in found)),[])
        self.assertTrue(is_voice(dict(name='Renamed',audio_type='windows_voice',category='WTF')))

    def test_suggestion_context_protects_unknown_speech_and_maps_auto_transcript(self):
        from types import SimpleNamespace
        window=SimpleNamespace(cuts=CutPlan((CutRange(1,2),)),trim=TrimRange(0,6),
            edits=EditOptions(speed=2),media=SimpleNamespace(has_audio=True),auto_candidate=None,pulse_candidate=None)
        self.assertEqual(caption_context(window)[1],[(0,2.5)])
        window.auto_candidate=({},[dict(start=3,end=4,text='speech')])
        self.assertEqual(caption_context(window)[1],[(1,1.5)])
        window.auto_candidate=None
        window.pulse_candidate=({'timeline':[dict(kind='shot',start=0,end=3),dict(kind='freeze',source_time=3,duration=2)]},None)
        self.assertEqual(caption_context(window)[1],[(0,.5),(.5,1)])

    def test_phrase_alias_creator_tags_and_punctuation(self):
        item=dict(id='import.abc',name='OH HELL NAH!',kind='sfx',category='Imported',
                  artist='Test Performer',transcript="Ain’t no way!",tags='gaming',aliases='absolutely not')
        for query in ('oh hell nah','nope','disbelief','nah','aint no way','test performer','gaming','absolutely not'):
            self.assertTrue(matches(item,query),query)
        self.assertTrue(in_category(item,'Disbelief'))
        self.assertTrue(in_category(item,'Imported'))
        self.assertFalse(matches(item,'explosion'))
        self.assertTrue(matches(dict(item,name='WHAT THE FUCK?!'),'wtf'))

    def test_rights_are_not_inferred_from_license_tags(self):
        item=dict(id='import.abc',licence='royalty-free')
        self.assertEqual(rights_label(item),'Unverified')
        item['rights_status']='Licensed / permission-cleared'
        self.assertEqual(rights_label(item),item['rights_status'])

    def test_search_is_a_plain_encoded_external_query(self):
        url=discovery_url('WHAT THE FUCK?! & bruh #1')
        self.assertEqual(urlparse(url).netloc,'www.google.com')
        self.assertEqual(parse_qs(urlparse(url).query)['q'],['WHAT THE FUCK?! & bruh #1 reaction sound audio licence'])
        for value in ('', 'x'*201):
            with self.assertRaises(ValueError):discovery_url(value)


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS')=='1','Opt-in Windows Tk integration')
class SoundboardWindowsTests(unittest.TestCase):
    pump=fixture.PulsePlanUITests.pump

    def setUp(self):
        gc.collect()
        fixture.PulsePlanUITests.setUp(self)
        env=patch.dict(os.environ,PULSE_REACTION_LIBRARY=str(self.folder/'library'))
        env.start();self.addCleanup(env.stop)

    def cleanup(self):
        fixture.PulsePlanUITests.cleanup(self)
        self.window=self.root=None
        gc.collect()

    def test_import_search_live_windows_audition_insert_and_export(self):
        w=self.window
        source=self.folder/'OH HELL NAH.wav'; mp3=self.folder/'WHAT THE FUCK.mp3'
        for path,freq in ((source,730),(mp3,910)):
            result=run([w.backend.ffmpeg,'-v','error','-f','lavfi','-i',f'sine=frequency={freq}:duration=0.6',str(path)],20)
            self.assertEqual(result.returncode,0,result.stderr)
        dialog=ReactionDialog(w,'sfx')
        dialog.search.set('old search')
        with patch('editor.reaction_tools.filedialog.askopenfilenames',return_value=(str(source),str(mp3),str(source))):
            dialog.import_asset()
        self.pump(lambda:not dialog.busy)
        self.assertIn('Added 2 · duplicates 1',dialog.note.cget('text'))
        self.assertEqual(dialog.search.get(),'')
        imported=[i for i in dialog.library.items('sfx') if i['id'].startswith('import.')]
        voice=next(i['id'] for i in imported if i['name']=='WHAT THE FUCK')
        recording=next(i['id'] for i in imported if i['name']=='OH HELL NAH')
        dialog.library.update_details(voice,dict(audio_type='windows_voice'))
        dialog.library.categorize([voice],'WTF')
        dialog.refresh_library()
        order=dialog.assets.get_children()
        self.assertLess(order.index(recording),order.index('comedy.boing'))
        self.assertLess(order.index('comedy.boing'),order.index(voice))
        dialog.audio_scope.set('My recordings');dialog.search.set('nope');self.root.update()
        keys=dialog.assets.get_children();self.assertEqual(len(keys),1)
        key=keys[0];dialog.assets.selection_set(key)
        dialog.preview_asset()
        # Calls the actual Windows audio API, with a real decoded WAV.
        self.pump(lambda:'Playing preview' in dialog.note.cget('text'))
        self.assertIn('Unverified',dialog.asset_label.cget('text'))
        dialog.stop_preview()
        details=ReactionDetails(dialog,key)
        details.values['aliases'].insert('1.0','absolutely not')
        details.values['artist'].insert('1.0','Fixture Performer')
        details.rights.set('Original recording');details.save();details.destroy()
        dialog.search.set('absolutely not');self.root.update()
        self.assertEqual(dialog.assets.get_children(),(key,))
        dialog.assets.selection_set(key);dialog.favourite()
        dialog.category.set('Favourites');self.root.update()
        self.assertEqual(dialog.assets.get_children(),(key,))
        dialog.assets.selection_set(key)
        w.cuts=CutPlan((CutRange(1,2),));w.edits=replace(w.edits,speed=2)
        w.edits=replace(w.edits,text=replace(w.edits.text,captions=(Caption(3,4,'OH HELL NAH!','Top'),)))
        dialog.suggest_reaction();self.root.update()
        self.assertFalse(w.edits.sounds)
        self.assertIn('Nothing added yet',dialog.suggestion_note)
        self.assertEqual(dialog.selected(),key)
        w.seek(3);dialog.insert()
        self.assertEqual(w.edits.sounds[0].at,1.)
        dialog.close();w.export()
        self.pump(lambda:w.last_export is not None or
                  (not w.exporter.busy and str(w.export_button.cget('state'))=='normal'))
        self.assertIsNotNone(w.last_export,w.note.cget('text'))
        pcm=subprocess.run([w.backend.ffmpeg,'-v','error','-i',str(w.last_export),'-vn','-ar','48000','-ac','1','-f','f32le','-'],capture_output=True,timeout=20)
        self.assertEqual(pcm.returncode,0,pcm.stderr)
        samples=array('f');samples.frombytes(pcm.stdout)
        self.assertLess(max(abs(v) for v in samples[:40000]),.001)
        self.assertGreater(max(abs(v) for v in samples[50000:70000]),.1)
        self.assertEqual(ReactionLibrary().metadata(key)['aliases'],'absolutely not')
        self.assertIn(key,ReactionLibrary().preferences()['favourites'])
        if os.environ.get('PULSE_VERIFICATION_DIR'):
            folder=Path(os.environ['PULSE_VERIFICATION_DIR']);folder.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(w.last_export,folder/'soundboard-windows-demo.mp4')

    def test_discovery_and_missing_asset_are_recoverable(self):
        dialog=ReactionDialog(self.window,'sfx')
        with patch('editor.meme_finder.MemeFinder') as finder:
            dialog.find_sounds()
            finder.assert_called_once_with(dialog)
        dialog.assets.selection_set('original.rimshot')
        with patch.object(dialog.library,'resolve',side_effect=ValueError('Missing local asset')):
            dialog.preview_asset();self.pump(lambda:'Missing local asset' in dialog.note.cget('text'))
        self.assertFalse(self.window.edits.sounds)


@unittest.skipUnless(os.environ.get('PULSE_RUN_FFMPEG_TESTS')=='1','Opt-in real audio render')
class SoundboardAudioTests(unittest.TestCase):
    pcm=render_fixture.MediaLibraryRenderTests.pcm
    tone=render_fixture.MediaLibraryRenderTests.tone

    def test_import_normalization_dedup_cuts_speed_duck_and_preview_export_agree(self):
        with tempfile.TemporaryDirectory() as temporary,patch.dict(os.environ,PULSE_REACTION_LIBRARY=temporary):
            folder=Path(temporary);self.ffmpeg=shutil.which('ffmpeg');probe=shutil.which('ffprobe')
            source=folder/'video.mp4';sound=folder/'reaction.mp3'
            for command in (
                [self.ffmpeg,'-v','error','-f','lavfi','-i','color=s=320x180:r=30','-f','lavfi','-i','sine=frequency=400:duration=6','-t','6','-c:v','libx264','-c:a','aac',str(source)],
                [self.ffmpeg,'-v','error','-f','lavfi','-i','sine=frequency=1100:duration=0.8','-af','volume=0.25','-metadata','license=fixture tag',str(sound)]):
                result=run(command,20);self.assertEqual(result.returncode,0,result.stderr)
            library=ReactionLibrary();key=library.import_file(sound,'sfx',self.ffmpeg,probe)
            self.assertGreater(library.metadata(key)['import_gain_db'],10)
            self.assertEqual(rights_label(library.metadata(key)),'Unverified')
            library.update_details(key,dict(aliases='nope',rights_status='Original recording',attribution='Fixture credit'))
            library.categorize([key],'My reactions');library.remember(key,True)
            saved=library.metadata(key)
            self.assertEqual(library.import_file(sound,'sfx',self.ffmpeg,probe),key)
            self.assertEqual(library.metadata(key),saved)
            library.resolve(key).unlink()  # Only this temporary fixture's owned media.
            library.import_file(sound,'sfx',self.ffmpeg,probe)
            self.assertEqual(library.metadata(key)['attribution'],'Fixture credit')
            bad=folder/'broken.wav';bad.write_bytes(b'broken')
            result=library.import_many([bad,sound],'sfx',self.ffmpeg,probe)
            self.assertEqual(len(result['errors']),1);self.assertEqual(result['duplicates'],[key])
            from editor.media import probe_media
            media=probe_media(probe,source);trim=TrimRange(0,6);cuts=CutPlan((CutRange(1,2),))
            cue=SoundCue(key,1,volume=.8,duck_source=.2)
            edits=EditOptions(speed=2,sounds=(cue,));output=folder/'output.mp4'
            result=run(build_export_command(self.ffmpeg,media,trim,output,edits,cuts=cuts),40)
            self.assertEqual(result.returncode,0,result.stderr)
            actual=self.pcm(output)
            self.assertAlmostEqual(probe_media(probe,output).duration,2.5,delta=.06)
            self.assertLess(self.tone(actual,.2,1100),.003)
            self.assertGreater(self.tone(actual,1.2,1100),.05)
            self.assertLess(self.tone(actual,1.2,400),self.tone(actual,.2,400)*.4)
            # Source 3.2 maps to output 1.1 after cut and 2x speed.
            preview=subprocess.run(audio_preview_command(self.ffmpeg,media,3.2,trim,cuts,edits),capture_output=True,timeout=20)
            self.assertEqual(preview.returncode,0,preview.stderr)
            data=array('h');data.frombytes(preview.stdout);values=[v/32768 for v in data[::2]]
            self.assertAlmostEqual(self.tone(values,.1,1100),self.tone(actual,1.2,1100),delta=.015)


if __name__=='__main__':unittest.main()
