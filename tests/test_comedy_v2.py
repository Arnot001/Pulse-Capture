import copy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from editor.models import MediaInfo, TrimRange
from editor.pulse_plan import starter_plan, source_identity, validate_pulse_plan, timeline_positions, pulse_editor_state
from editor.reaction_library import ReactionLibrary, SFX
from editor.reactions import SoundCue, VisualCue
from editor.typography import CaptionStyle
from editor.text_overlay import TextResources
from editor.ffmpeg_export import build_export_command
from editor.preview import preview_command


class ComedyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, PULSE_REACTION_LIBRARY=str(self.root/'library'))
        self.env.start(); self.addCleanup(self.env.stop)
        self.source = self.root/'source.mp4'; self.source.write_bytes(b'source')
        self.media = MediaInfo(self.source, 6, 640, 360, 30, True)
        self.plan = starter_plan(self.media, source_identity(self.media, threading.Event()))
        self.plan.update(version=2, timeline=[dict(kind='shot', start=0, end=1),
                         dict(kind='freeze', source_time=1), dict(kind='shot', start=1, end=2)],
                         sfx=[dict(asset_id='comedy.boing', at=1, duck_source=.35)],
                         captions=[dict(start=1,end=2.8,text='THAT WAS PERSONAL',zone='top',basis='joke',
                                        typography=dict(highlight='PERSONAL'))])

    def test_v1_and_output_freeze_default(self):
        validate_pulse_plan(starter_plan(self.media,self.plan['source']),self.media)
        validate_pulse_plan(self.plan,self.media)
        self.assertEqual(timeline_positions(self.plan),[(0,1),(1,2.8),(2.8,3.8)])
        self.plan['freeze_duration']=2.4
        self.assertAlmostEqual(timeline_positions(self.plan)[-1][1],4.4)
        self.plan['timeline'][1]['duration']=.5
        self.assertAlmostEqual(timeline_positions(self.plan)[-1][1],2.5)

    def test_strict_v2_rejects_unsafe_and_unsupported(self):
        changes = [lambda p:p['sfx'][0].update(asset_id='../secret.wav'),
                   lambda p:p['sfx'][0].update(asset_id='https://example.com/a'),
                   lambda p:p['sfx'][0].update(asset_id='unknown.sound'),
                   lambda p:p['sfx'][0].update(at=True),
                   lambda p:p['sfx'][0].update(at=3.8),
                   lambda p:p['sfx'][0].update(volume=float('nan')),
                   lambda p:p['sfx'][0].update(duck_source=-1),
                   lambda p:p['sfx'][0].update(command='ffmpeg'),
                   lambda p:p.update(overlays=[dict(kind='gif',asset_id='emoji.skull',start=0,end=1)]),
                   lambda p:p.update(overlays=[dict(kind='emoji',asset_id='emoji.skull',start=0,end=5)]),
                   lambda p:p['captions'][0].update(typography=dict(animation='morph')),
                   lambda p:p['captions'][0].update(typography=dict(highlight='absent')),
                   lambda p:p.update(freeze_duration=.111),
                   lambda p:p.update(version=1)]
        for change in changes:
            plan=copy.deepcopy(self.plan);change(plan)
            with self.subTest(plan=plan),self.assertRaises(ValueError):validate_pulse_plan(plan,self.media)

    def test_original_library_is_distinct_and_persistent(self):
        library=ReactionLibrary()
        digests=set()
        for key in SFX:
            path=library.resolve(key); before=path.stat().st_mtime_ns
            digests.add(hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(library.resolve(key).stat().st_mtime_ns,before)
        self.assertEqual(len(digests),19)
        library.remember('comedy.boing',True); library.remember('emoji.skull')
        self.assertIn('comedy.boing',ReactionLibrary().preferences()['favourites'])
        self.assertEqual(ReactionLibrary().preferences()['recent'][0],'emoji.skull')

    def test_pipeline_uses_output_clock_and_safe_resources(self):
        self.plan['overlays']=[dict(kind='emoji',asset_id='emoji.skull',start=1,end=2.8,animation='pop')]
        assembled=replace(self.media,path=self.root/'review.mp4',duration=3.8,width=1080,height=1920)
        trim,cuts,edits=pulse_editor_state(self.plan,assembled)
        with TextResources(edits.text) as resources:
            command=build_export_command('ffmpeg',assembled,trim,self.root/'out.mp4',edits,text_resources=resources)
            graph=command[command.index('-filter_complex')+1]
            self.assertIn('adelay=48000S',graph)
            self.assertIn('latency=true',graph)
            self.assertNotIn('THAT WAS PERSONAL',' '.join(command))
            preview=preview_command('ffmpeg',assembled,1.4,360,640,edits,False,resources,trim,cuts)
            self.assertIn('overlay=', ' '.join(preview))
            ass='\n'.join(p.read_text(encoding='utf-8') for p in Path(resources.temp.name).glob('*.ass'))
            self.assertIn('DejaVu Sans,88',ass)
            self.assertIn('PERSONAL',ass)
        with self.assertRaises(ValueError):
            build_export_command('ffmpeg',assembled,trim,assembled.path,edits)


if __name__=='__main__':unittest.main()
