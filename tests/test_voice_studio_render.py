"""Actual narrated MP4 and preview audio parity with cuts, speed, music and SFX."""
from dataclasses import replace
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from editor.audio_preview import audio_preview_command
from editor.cuts import CutPlan, CutRange
from editor.ffmpeg_export import build_export_command
from editor.models import MediaInfo, TrimRange
from editor.music import Music, IMPORT_LABEL
from editor.narration import Narration
from editor.reactions import SoundCue
from editor.transforms import EditOptions
from editor.voice_assets import import_audio
from tests.test_ai_narration_render import execute, make_wav

FFMPEG = shutil.which('ffmpeg')


@unittest.skipUnless(FFMPEG, 'FFmpeg unavailable')
class VoiceStudioRenderTests(unittest.TestCase):
    def test_narration_with_cut_speed_music_and_seek(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LOCALAPPDATA':tmp, 'PULSE_REACTION_LIBRARY':str(Path(tmp)/'reactions')}):
            root = Path(tmp)
            voice = root/'voice.wav'
            make_wav(voice, 660, 3)
            cue_file = import_audio(os.environ.get('PULSE_TEST_CONVERTED', str(voice)), FFMPEG)
            music = root/'music.wav'
            make_wav(music, 220, 8, 1200)
            source = root/'video.mp4'
            execute([FFMPEG, '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30:d=8',
                     '-c:v', 'libx264', '-threads', '2', str(source)])
            media = MediaInfo(source, 8, 320, 180, 30, False)
            trim, cuts = TrimRange(0, 8), CutPlan((CutRange(2, 4),))
            edits = replace(EditOptions(), speed=1.5,
                narration=Narration(str(cue_file), .5, .8, .25),
                music=Music(True, IMPORT_LABEL, music, fade_in=False, fade_out=False),
                sounds=(SoundCue('comedy.pop', 3.5),))
            output = root/'narrated.mp4'
            execute(build_export_command(FFMPEG, media, trim, output, edits, cuts=cuts))
            preview = subprocess.run(audio_preview_command(FFMPEG, media, 0, trim, cuts, edits),
                                     capture_output=True, timeout=60)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            decoded = subprocess.run([FFMPEG, '-v', 'error', '-i', str(output), '-vn',
                                      '-ar', '48000', '-ac', '2', '-f', 's16le', 'pipe:1'],
                                     capture_output=True, timeout=60)
            self.assertEqual(decoded.returncode, 0, decoded.stderr)
            self.assertAlmostEqual(len(preview.stdout)/(48000*4), 4, delta=.01)
            self.assertAlmostEqual(len(decoded.stdout)/(48000*4), 4, delta=.05)
            # AAC permits sample differences. Compare 100 ms energy envelopes.
            def envelopes(blob):
                values = struct.unpack('<'+'h'*(len(blob)//2), blob)
                return [sum(x*x for x in values[i:i+9600])/9600 for i in range(0, 4*96000, 9600)]
            a, b = envelopes(preview.stdout), envelopes(decoded.stdout)
            error = sum(abs(x-y) for x,y in zip(a,b)) / max(1,sum(a))
            self.assertLess(error, .1)
            seek = subprocess.run(audio_preview_command(FFMPEG, media, 5, trim, cuts, edits),
                                  capture_output=True, timeout=60)
            self.assertEqual(seek.returncode, 0, seek.stderr)
            self.assertAlmostEqual(len(seek.stdout)/(48000*4), 2, delta=.01)


if __name__ == '__main__':
    unittest.main()
