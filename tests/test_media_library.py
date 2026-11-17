from dataclasses import replace
import hashlib
import json
import tempfile
import threading
from pathlib import Path
import unittest

from editor.reaction_library import ReactionLibrary, SFX, LEGACY_SFX, bundled_gifs, inspect_gif
from editor.sound_design import RECIPES, CATEGORIES
from editor.music import Music
from editor.music_library import MusicLibrary, description_credit, validate_record
from editor.music_mix import filters, input_loops


class MediaLibraryTests(unittest.TestCase):
    def test_populated_original_catalogues_and_gif_structure(self):
        with tempfile.TemporaryDirectory() as folder:
            library=ReactionLibrary(folder)
            self.assertGreaterEqual(len(library.items('sfx')),150)
            self.assertEqual({x['category'] for x in library.items('sfx')},set(CATEGORIES))
            self.assertEqual(len(LEGACY_SFX),19)
            self.assertEqual(len({repr(v[2]) for v in RECIPES.values()}),len(RECIPES))
            self.assertGreaterEqual(len(library.items('gif')),60)
            hashes=set()
            for item in library.items('gif'):
                data=library.resolve(item['id']).read_bytes()
                w,h,delays=inspect_gif(data)
                self.assertEqual((w,h),(256,256))
                self.assertGreater(len(delays),1)
                self.assertAlmostEqual(sum(delays),item['duration'])
                self.assertEqual(hashlib.sha256(data).hexdigest(),item['sha256'])
                self.assertTrue(library.thumbnail(item['id']).is_file())
                self.assertTrue(item['licence_record'])
                hashes.add(item['sha256'])
            self.assertEqual(len(hashes),len(bundled_gifs()))
            self.assertEqual(list(Path(folder).iterdir()),[])  # Browsing creates no user files.

    def test_batch_categories_preserve_preferences_and_bundles(self):
        with tempfile.TemporaryDirectory() as folder:
            library=ReactionLibrary(folder)
            library.remember('comedy.boing',True)
            library.remember('reaction.laugh')
            library.categorize(['comedy.boing','reaction.laugh'],'My favourites')
            self.assertIn('comedy.boing',library.preferences()['favourites'])
            self.assertEqual(library.preferences()['recent'][0],'reaction.laugh')
            self.assertEqual(next(x for x in library.items('gif') if x['id']=='reaction.laugh')['category'],'My favourites')
            self.assertEqual(bundled_gifs()['reaction.laugh']['category'],'Faces')
            for category in ('','All','Recent','x'*49,'bad\nname'):
                with self.assertRaises(ValueError):library.categorize(['comedy.boing'],category)

    def test_bundled_file_import_dedup_without_decode(self):
        with tempfile.TemporaryDirectory() as folder:
            library=ReactionLibrary(folder)
            path=library.resolve('reaction.facepalm')
            result=library.import_many([path,path], 'gif','no-ffmpeg-needed','no-probe-needed')
            self.assertEqual(result['added'],[])
            self.assertEqual(result['duplicates'],['reaction.facepalm']*2)
            self.assertEqual(result['errors'],[])
            cancel=threading.Event()
            result=library.import_many([path,path], 'gif','unused','unused',
                                       lambda *_:cancel.set(),cancel)
            self.assertEqual(result['duplicates'],['reaction.facepalm'])

    def test_credit_is_exact_and_never_invented(self):
        record=dict(name='Example',artist='Artist',source='YouTube Audio Library',licence='Creative Commons Attribution',
                    requires_attribution=True,attribution='Example by Artist\nExact licence and source supplied by creator')
        self.assertEqual(description_credit(record),record['attribution'])
        with self.assertRaises(ValueError):validate_record(dict(record,attribution=''))
        with self.assertRaises(ValueError):validate_record(dict(record,requires_attribution=False))
        self.assertEqual(description_credit(dict(record,licence='YouTube Audio Library licence',requires_attribution=False)),'')
        with tempfile.TemporaryDirectory() as folder:
            library=MusicLibrary(folder)
            with self.assertRaises(ValueError):library.path(dict(id='../escape',suffix='.wav'))

    def test_trim_validation_loop_and_preview_offset_share_fades(self):
        music=Music(True,trim_start=.4,trim_end=1.2,duck_dialogue=True)
        music.validate()
        self.assertFalse(input_loops(music))
        chain=','.join(filters(music,1.5,2,3.5))
        self.assertIn('aloop=loop=-1:size=38400',chain)
        self.assertIn('afade=t=out:st=3.000000:d=0.500000',chain)
        self.assertIn('atrim=start=2.000000000:end=3.500000000',chain)
        for changes in (dict(trim_start=-1),dict(trim_end=.3),dict(trim_start=float('nan')),
                        dict(trim_end=None),dict(duck_dialogue='yes')):
            with self.assertRaises(ValueError):replace(music,**changes).validate()


if __name__=='__main__':unittest.main()
