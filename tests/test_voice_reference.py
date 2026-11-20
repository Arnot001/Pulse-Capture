"""Reference permission, immutable staging, failure cleanup and catalogue tests."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

from editor.voice_assets import digest
from editor.voice_catalogue import Catalogue
from editor.voice_reference import prepare_reference, reference_labels, run_local
from tests.test_voice_studio_v2 import tone


LABELS = dict(name='Test reference', permission='own voice', provenance='Test-only generated audio',
              consent=True, presentation='Male', style='Comedy', language='English', accent='Unspecified')


@unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg unavailable')
class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source.wav'
        tone(self.source, seconds=4)

    def prepare(self):
        result = prepare_reference(self.source, shutil.which('ffmpeg'))
        self.addCleanup(result.close)
        return result

    def fake_extract(self, reference, destination, cancel=None):
        Path(destination).write_bytes(b'fixture; validation mocked only in catalogue transaction tests')
        return {'device':'cpu', 'fixture':True}

    def test_preparation_keeps_original_and_reports_audio(self):
        before = digest(self.source)
        ref = self.prepare()
        self.assertEqual(digest(self.source), before)
        self.assertEqual(digest(ref.original), before)
        self.assertEqual(ref.source_sha256, before)
        self.assertEqual(ref.info['rate'], 22050)
        self.assertAlmostEqual(ref.info['duration'], 4, places=3)
        self.assertGreater(ref.info['active_seconds'], 3)
        folder = ref.wav.parent
        ref.close()
        self.assertFalse(folder.exists())

    def test_corrupt_silent_short_long_clipped_and_remote_playlist_rejected(self):
        bad = self.root/'bad.wav'
        for content in (b'not wave audio', b'#EXTM3U\nhttp://127.0.0.1:9/private.wav'):
            bad.write_bytes(content)
            with self.assertRaises(ValueError):
                prepare_reference(bad, shutil.which('ffmpeg'))
        for seconds, sample in ((1, b'\x10\x00'), (61, b'\x10\x00'), (4, b'\0\0'), (4, b'\xff\x7f')):
            with wave.open(str(bad), 'wb') as writer:
                writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(22050)
                writer.writeframes(sample*(22050*seconds))
            with self.assertRaises(ValueError):
                prepare_reference(bad, shutil.which('ffmpeg'))

    def test_permission_and_provenance_required_before_extraction(self):
        ref = self.prepare()
        catalogue = Catalogue(self.root/'library')
        for changes in ({'consent':False}, {'permission':'assumed'}, {'provenance':''}, {'name':''},
                        {'presentation':'guessed'}, {'language':False}):
            with patch('editor.voice_catalogue.extract_reference') as extract:
                with self.assertRaises(ValueError):
                    catalogue.add_reference(ref, dict(LABELS, **changes))
                extract.assert_not_called()
        self.assertFalse(catalogue.root.exists())

    def test_catalogue_persists_private_reference_and_reuses_duplicate(self):
        ref = self.prepare()
        catalogue = Catalogue(self.root/'library')
        with patch('editor.voice_catalogue.extract_reference', side_effect=self.fake_extract) as extract, \
             patch('editor.voice_catalogue.validate_embedding'):
            voice = catalogue.add_reference(ref, LABELS)
            duplicate = Catalogue(catalogue.root).add_reference(ref, dict(LABELS, name='Another label'))
        self.assertEqual(voice.id, duplicate.id)
        extract.assert_called_once()
        self.assertEqual(digest(voice.reference_file), ref.source_sha256)
        loaded = Catalogue(catalogue.root)
        self.assertEqual(loaded.search(category='Male')[0].id, voice.id)
        self.assertEqual(len(loaded.state['custom']), 1)
        self.assertIn('User-provided', voice.metadata_origin)
        self.assertEqual(voice.permission, 'own voice')
        loaded.favourite(voice.id)
        self.assertEqual(Catalogue(catalogue.root).search(favourites=True)[0].id, voice.id)
        self.assertTrue(all(v.accent == 'Preserves source pronunciation' for v in Catalogue(self.root/'empty').voices()))

    def test_failed_extraction_validation_or_save_does_not_publish(self):
        ref = self.prepare()
        catalogue = Catalogue(self.root/'library')
        for failing in ('extract_reference', 'validate_embedding', 'save'):
            with patch('editor.voice_catalogue.extract_reference', side_effect=self.fake_extract), \
                 patch('editor.voice_catalogue.validate_embedding'), \
                 patch.object(catalogue, 'save') as save:
                if failing == 'save':
                    save.side_effect = OSError('disk full')
                    with self.assertRaises(OSError):
                        catalogue.add_reference(ref, LABELS)
                else:
                    with patch('editor.voice_catalogue.'+failing, side_effect=ValueError('invalid')):
                        with self.assertRaises(ValueError):
                            catalogue.add_reference(ref, LABELS)
            self.assertEqual(catalogue.state['custom'], [])
            self.assertFalse(list(catalogue.root.glob('reference-*')))

    def test_cancel_prevents_publish_and_stops_active_process(self):
        ref = self.prepare()
        cancel = threading.Event()
        cancel.set()
        catalogue = Catalogue(self.root/'library')
        with patch('editor.voice_catalogue.extract_reference') as extract:
            with self.assertRaisesRegex(ValueError, 'cancelled'):
                catalogue.add_reference(ref, LABELS, cancel)
            extract.assert_not_called()
        cancel.clear()
        started = self.root/'started'
        def cancel_when_started():
            until = time.monotonic()+5
            while not started.exists() and time.monotonic() < until:
                time.sleep(.01)
            cancel.set()
        thread = threading.Thread(target=cancel_when_started)
        thread.start()
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            run_local([sys.executable, '-c', "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); time.sleep(30)", str(started)], cancel)
        thread.join()
        self.assertTrue(started.exists())
        self.assertEqual(digest(self.source), ref.source_sha256)


if __name__ == '__main__':
    unittest.main()
