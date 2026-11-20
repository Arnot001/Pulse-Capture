"""Opt-in CPU extraction/reuse; caller supplies an authorised reference + labels JSON."""
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from editor.voice_assets import VoiceSettings, digest, wav_info
from editor.voice_catalogue import Catalogue
from editor.voice_conversion import available, convert_voice, runtime_python
from editor.voice_reference import prepare_reference, validate_embedding, run_local
from editor.voice_tools import synthesize_windows


@unittest.skipUnless(os.environ.get('PULSE_RUN_REFERENCE_MODEL_TESTS') == '1', 'Opt-in authorised reference CPU test')
class ReferenceModelTests(unittest.TestCase):
    def test_extract_reuse_safe_tensor_and_timing_without_network(self):
        self.assertTrue(available(), 'Install the runtime explicitly first')
        source = Path(os.environ['PULSE_REFERENCE_TEST_AUDIO'])
        labels = json.loads(Path(os.environ['PULSE_REFERENCE_TEST_LABELS']).read_text(encoding='utf-8'))
        before = digest(source)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reference = prepare_reference(source, shutil.which('ffmpeg'))
            self.addCleanup(reference.close)
            catalogue = Catalogue(root/'library')
            # Deny socket use in the actual runtime subprocess, not just the host test.
            wrapper = ("import sys,runpy; "
                       "sys.addaudithook(lambda e,a: (_ for _ in ()).throw(RuntimeError('Network forbidden')) "
                       "if e in ('socket.connect','socket.getaddrinfo','socket.sendto','socket.sendmsg') else None); "
                       "p=sys.argv.pop(1); runpy.run_path(p,run_name='__main__')")
            def offline(command, *args, **kwargs):
                if command[1].endswith('voice_conversion_worker.py'):
                    command = [command[0], '-c', wrapper] + command[1:]
                return run_local(command, *args, **kwargs)
            with patch('editor.voice_reference.run_local', side_effect=offline):
                voice = catalogue.add_reference(reference, labels)
            self.assertEqual(Catalogue(catalogue.root).add_reference(reference, labels).id, voice.id)
            self.assertEqual(digest(source), before)
            validate_embedding(voice.model)
            invalid = root/'invalid.pth'
            for value in ('torch.zeros(1,255,1)', "torch.full((1,256,1),float('nan'))", 'torch.zeros(1,256,1,dtype=torch.int64)'):
                subprocess.run([str(runtime_python()), '-c', 'import torch,sys; torch.save('+value+',sys.argv[1])', str(invalid)], check=True)
                with self.assertRaises(ValueError):
                    validate_embedding(invalid)
            raw = root/'spoken.wav'
            synthesize_windows('Well, that was a brilliant plan. Absolutely nothing could possibly go wrong.', raw)
            with wave.open(str(raw), 'rb') as reader:
                params, pcm = reader.getparams(), reader.readframes(reader.getnframes())
            unit = params.sampwidth*params.nchannels
            mid = len(pcm)//unit//2*unit
            pause = mid/(params.framerate*unit)
            performance = root/'performance.wav'
            with wave.open(str(performance), 'wb') as writer:
                writer.setparams(params)
                writer.writeframes(pcm[:mid]+bytes(round(.8*params.framerate)*unit)+pcm[mid:])
            narration_hash = digest(performance)
            first = convert_voice(performance, voice.model, shutil.which('ffmpeg'), VoiceSettings(), root)
            second = convert_voice(performance, voice.model, shutil.which('ffmpeg'), VoiceSettings(), root)
            self.assertEqual(digest(first), digest(second))
            self.assertEqual(digest(performance), narration_hash)
            self.assertAlmostEqual(wav_info(first)['duration'], wav_info(performance)['duration'], delta=.001)
            with wave.open(str(first), 'rb') as reader:
                reader.setpos(round((pause+.15)*reader.getframerate()))
                pcm = reader.readframes(round(.5*reader.getframerate()))
            self.assertLess(max(map(abs, struct.unpack('<'+'h'*(len(pcm)//2), pcm))), 4)


if __name__ == '__main__':
    unittest.main()
