"""Opt-in real, local neural conversion. Never download models or call paid APIs."""
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

from editor.voice_assets import VoiceSettings, digest, import_audio, wav_info
from editor.voice_conversion import available, convert_voice, runtime_root
from editor.voice_catalogue import Catalogue
from editor.voice_tools import synthesize_windows


@unittest.skipUnless(os.environ.get('PULSE_RUN_VOICE_MODEL_TESTS') == '1', 'Opt-in installed CPU model test')
class ConversionTests(unittest.TestCase):
    def setUp(self):
        if not available() or not shutil.which('ffmpeg'):
            self.skipTest('Install the local runtime and FFmpeg first')
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        raw = self.root/'spoken.wav'
        synthesize_windows('Well, that was a brilliant plan. Absolutely nothing could possibly go wrong. Oh. It did.', raw)
        # Insert a known 800 ms deliberate pause without transcription or synthesis.
        with wave.open(str(raw), 'rb') as reader:
            params, pcm = reader.getparams(), reader.readframes(reader.getnframes())
        midpoint = (len(pcm)//(params.sampwidth*params.nchannels)//2)*params.sampwidth*params.nchannels
        gap = bytes(round(params.framerate*.8)*params.sampwidth*params.nchannels)
        paused = self.root/'performance.wav'
        with wave.open(str(paused), 'wb') as writer:
            writer.setparams(params)
            writer.writeframes(pcm[:midpoint]+gap+pcm[midpoint:])
        self.pause_start = midpoint / (params.framerate*params.sampwidth*params.nchannels)
        self.source = import_audio(paused, shutil.which('ffmpeg'), self.root)
        self.voice = runtime_root()/'checkpoints/base_speakers/ses/en-br.pth'

    def test_real_conversion_timing_pause_and_reproducibility(self):
        before = digest(self.source)
        first = convert_voice(self.source, self.voice, shutil.which('ffmpeg'), VoiceSettings(), self.root)
        second = convert_voice(self.source, self.voice, shutil.which('ffmpeg'), VoiceSettings(), self.root)
        self.assertEqual(digest(self.source), before)
        self.assertNotEqual(digest(first), before)
        self.assertEqual(digest(first), digest(second))
        self.assertNotEqual(first, second)
        self.assertAlmostEqual(wav_info(first)['duration'], wav_info(self.source)['duration'], delta=.001)
        with wave.open(str(first), 'rb') as reader:
            reader.setpos(round((self.pause_start+.15)*reader.getframerate()))
            pcm = reader.readframes(round(.5*reader.getframerate()))
            values = struct.unpack('<'+'h'*(len(pcm)//2), pcm)
            self.assertLess(max(map(abs, values)), 4)
        metadata = json.loads(first.with_suffix('.json').read_text())
        self.assertEqual(metadata['backend']['device'], 'cpu')
        self.assertEqual(metadata['source_sha256'], before)
        self.assertEqual(metadata['voice_sha256'], digest(self.voice))

    def test_cancel_retains_source_and_does_not_publish_result(self):
        cancellation = threading.Event()
        cancellation.set()
        with self.assertRaisesRegex(ValueError, 'cancelled'):
            convert_voice(self.source, self.voice, shutil.which('ffmpeg'), VoiceSettings(), self.root,
                          cancel=cancellation)
        self.assertTrue(self.source.exists())
        self.assertFalse(list(self.root.glob('converted-*.wav')))

    def test_permitted_embedding_import(self):
        manifest = self.root/'voice.json'
        manifest.write_text(json.dumps({'name':'Licensed test stock speaker', 'model':str(self.voice),
            'permission':'licensed', 'provenance':'https://huggingface.co/myshell-ai/OpenVoiceV2 · MIT',
            'presentation':'Unspecified', 'categories':['Documentary']}), encoding='utf-8')
        catalogue = Catalogue(self.root/'library')
        voice = catalogue.import_voice(manifest)
        self.assertTrue(Path(voice.model).exists())
        self.assertEqual(catalogue.search(category='Documentary')[0].id, voice.id)
        invalid = self.root/'invalid.pth'
        invalid.write_bytes(b'not a torch embedding')
        data = json.loads(manifest.read_text(encoding='utf-8'))
        data['model'] = str(invalid)
        manifest.write_text(json.dumps(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'valid, safe'):
            catalogue.import_voice(manifest)


if __name__ == '__main__':
    unittest.main()
