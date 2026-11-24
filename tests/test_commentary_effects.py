"""Effect preview and real FFmpeg filter validation; never modify source WAVs."""
from pathlib import Path
import math
import shutil
import subprocess
import tempfile
import threading
import unittest
import wave

from editor.commentary_effects import (
    EFFECTS, render_effect_audition, validate_effect, voice_effect_filters)
from editor.voice_assets import wav_info


def sample(path):
    with wave.open(str(path),'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(44100)
        import array
        audio=array.array('h',(int(9000*math.sin(2*math.pi*370*i/44100))
                               for i in range(44100*2)))
        out.writeframes(audio.tobytes())


class EffectParametersTests(unittest.TestCase):
    def test_clean_voice_strength_zero_is_exact_bypass(self):
        for fx in EFFECTS:
            self.assertEqual(voice_effect_filters(fx,0.),[])
        self.assertEqual(voice_effect_filters('None',1.),[])

    def test_no_arbitrary_audio_filter_expression_accepted(self):
        for bad in ('Aecho', 'none', 'aecho=1:1:200:1', '', None, 12):
            with self.assertRaises(ValueError):
                validate_effect(bad,.5)
        for bad in (-.1,1.1,float('inf'),float('nan'),'0.5',None,True):
            with self.assertRaises(ValueError):
                validate_effect('Echo',bad)


@unittest.skipUnless(shutil.which('ffmpeg'), 'Real FFmpeg required')
class LocalEffectPreviewTests(unittest.TestCase):
    def test_real_echo_reverb_chorus_previews_are_pcm_and_non_destructive(self):
        with tempfile.TemporaryDirectory() as tmp:
            mic=Path(tmp)/'mic.wav'
            sample(mic)
            before=mic.read_bytes()
            for effect in ('Echo','Reverb','Chorus'):
                with self.subTest(effect=effect):
                    result=render_effect_audition(
                        shutil.which('ffmpeg'),mic,.3,.8,effect,.75)
                    path,start,length,temporary=result
                    try:
                        self.assertTrue(temporary)
                        self.assertEqual(start,0.)
                        self.assertAlmostEqual(length,.8)
                        info=wav_info(path)
                        self.assertAlmostEqual(info['duration'],.8,delta=.01)
                        self.assertEqual(info['channels'],2)
                        self.assertEqual(info['rate'],48000)
                        self.assertGreater(path.stat().st_size,40000)
                    finally:
                        path.unlink(missing_ok=True)
            self.assertEqual(mic.read_bytes(),before)

    def test_cancelled_preview_leaves_source_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            mic=Path(tmp)/'mic.wav'
            sample(mic)
            original=mic.read_bytes()
            stop=threading.Event()
            stop.set()
            with self.assertRaisesRegex(ValueError,'cancelled'):
                render_effect_audition(
                    shutil.which('ffmpeg'),mic,0,1,'Reverb',1.,stop)
            self.assertEqual(mic.read_bytes(),original)

    def test_none_effect_returns_exact_original_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            mic=Path(tmp)/'mic.wav'
            sample(mic)
            result=render_effect_audition(
                shutil.which('ffmpeg'),mic,.4,.6,'None',.8)
            self.assertEqual(result,(mic,.4,.6,False))


if __name__ == '__main__':
    unittest.main()
