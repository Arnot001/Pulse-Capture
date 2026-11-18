"""Band safety and backwards compatibility, without external media or services."""
from dataclasses import replace
from pathlib import Path
import unittest

from editor.comedy_layout import regions, fit_caption, measure
from editor.models import MediaInfo
from editor.transforms import EditOptions, FULL_FRAME_FORMAT, SHORTS_FORMAT
from editor.text_overlay import Caption, TextOverlay
from editor.typography import CaptionStyle
from editor.reactions import VisualCue, ANIMATIONS
from editor.reaction_geometry import visual_bounds, positioned
from editor.pulse_plan import starter_plan, validate_pulse_plan, pulse_editor_state


class ComedyBandTests(unittest.TestCase):
    def setUp(self):
        self.media=MediaInfo(Path('landscape.mp4'),12,1920,1080,30,True)
        self.bands=regions((1920,1080))

    def test_readable_short_long_and_wide_captions_fit_or_reject(self):
        for text in ('NOPE','BRO REALLY SAID\nFUCK THE MISSION','DOGGO COMES FIRST',
                     'BRO ABANDONED THE ENTIRE MISSION','WWWWWWWWWWWWWWWWWWWW'):
            for band in self.bands.values():
                style=CaptionStyle(font_size=104)
                size,lines,height,padding=fit_caption(text,style,band)
                self.assertGreaterEqual(size,64)
                self.assertLessEqual(height+2*padding,band.height)
                self.assertTrue(all(measure(line,size)+2*padding<=band.width for line in lines))
        with self.assertRaisesRegex(ValueError,'readable'):
            fit_caption('W'*160,CaptionStyle(font_size=120),self.bands['bottom'])
        with self.assertRaises(ValueError):regions((1080,1920))

    def test_already_letterboxed_portrait_short_uses_existing_dark_bands(self):
        # This source has already been rendered to 9:16, with 16:9 gameplay
        # centred inside it. Do not reject it just because its file is portrait.
        self.assertEqual(regions((1080,1920)), self.bands)
        self.assertEqual(regions((1080,1920),360,640), regions((1920,1080),360,640))
        portrait=MediaInfo(Path('already-letterboxed-short.mp4'),12,1080,1920,30,True)
        edits=replace(EditOptions().with_format(portrait,FULL_FRAME_FORMAT),
                      comedy_bands=(portrait.width,portrait.height),
                      text=TextOverlay(captions=(
                          Caption(0,3,'BRO ABANDONED THE MISSION','Top',CaptionStyle(font_size=104)),
                          Caption(0,3,'TO PET THE DOG','Bottom',CaptionStyle(font_size=104)),
                      )))
        edits.validate(portrait)
        self.assertEqual(edits.output_size(portrait),(1080,1920))
        with self.assertRaisesRegex(ValueError,'9:16'):
            regions((1000,1400))

    def test_all_animation_bounds_and_drag_stay_in_zone(self):
        item=dict(width=256,height=256,duration=1)
        for zone,band in self.bands.items():
            for animation in ANIMATIONS:
                for at in (.01,.08,.2,.8):
                    for x,y in ((0,0),(1,1),(.5,.5)):
                        cue=VisualCue('emoji','emoji.skull',0,2,scale=.6,rotation=45,
                                      animation=animation,x=x,y=y,zone=zone)
                        box=visual_bounds(cue,1080,1920,at,item,self.bands)
                        self.assertGreaterEqual(box.x,band.x)
                        self.assertGreaterEqual(box.y,band.y)
                        self.assertLessEqual(box.x+box.side,band.x+band.width)
                        self.assertLessEqual(box.y+box.side,band.y+band.height)
                        moved=positioned(cue,band.x+50,band.y+50,1080,1920,at,item,self.bands)
                        self.assertTrue(0<=moved.x<=1 and 0<=moved.y<=1)

    def test_layout_validation_and_normal_crop(self):
        base=EditOptions().with_format(self.media,FULL_FRAME_FORMAT)
        good=replace(base,comedy_bands=(1920,1080),text=TextOverlay(captions=(
            Caption(0,3,'DOGGO COMES FIRST','Bottom',CaptionStyle(font_size=104)),)))
        good.validate(self.media)
        self.assertIsNone(good.with_format(self.media,SHORTS_FORMAT).comedy_bands)
        bad=replace(good,text=TextOverlay(captions=(Caption(0,3,'NOPE','Centre'),)))
        with self.assertRaisesRegex(ValueError,'Top or Bottom'):bad.validate(self.media)
        overlay=VisualCue('emoji','emoji.skull',0,3,zone='bottom')
        with self.assertRaisesRegex(ValueError,'require Comedy'):replace(base,overlays=(overlay,)).validate(self.media)

    def test_existing_plans_and_new_v2_bands(self):
        identity=dict(name=self.media.path.name,sha256='a'*64,duration=12,width=1920,height=1080,fps=30)
        plan=starter_plan(self.media,identity)
        validate_pulse_plan(plan,self.media)
        plan['version']=2;plan['output']['framing']='comedy_bands'
        plan['captions']=[dict(start=1,end=4,text='DOGGO COMES FIRST',zone='bottom',basis='joke')]
        plan['overlays']=[dict(kind='emoji',asset_id='emoji.skull',start=1,end=4,zone='top')]
        validate_pulse_plan(plan,self.media)
        assembled=replace(self.media,width=1080,height=1920,duration=7)
        _,_,edits=pulse_editor_state(plan,assembled)
        self.assertEqual(edits.comedy_bands,(1920,1080))
        self.assertEqual(edits.text.captions[0].style.font_size,104)
        plan['version']=1
        with self.assertRaises(ValueError):validate_pulse_plan(plan,self.media)


if __name__=='__main__':unittest.main()
