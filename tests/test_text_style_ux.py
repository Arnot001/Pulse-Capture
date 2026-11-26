"""Shared controls, legacy projects, exact render paths and Windows interaction."""
from dataclasses import asdict, replace
import gc
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import pytest

from editor.typography import CaptionStyle
from editor.text_overlay import TextOverlay, Caption, TextResources, text_filter
from editor.style_controls import FONT_SIZES, StyleControls, style_values
from editor.font_picker import font_rows, FontPicker
from editor.style_preferences import load_style_library, save_style_library, remember_font
from editor.project_file import encode, decode
from editor.caption_tools import CaptionDialog
from editor.text_style_dialog import TextStyleDialog
from tests import test_pulse_plan_ui as fixture


@pytest.mark.parametrize('size',FONT_SIZES+(67,150,240))
def test_sizes_allow_presets_and_custom_whole_values(size):
    values=asdict(CaptionStyle());theme=values.pop('theme');values['font_size']=str(size)
    assert style_values(values,theme).font_size==size


@pytest.mark.parametrize('value',('15','241','NaN','64.5',''))
def test_invalid_custom_sizes_do_not_coerce(value):
    values=asdict(CaptionStyle());theme=values.pop('theme');values['font_size']=value
    with pytest.raises(ValueError):style_values(values,theme)


def test_fonts_search_recent_favourites_and_missing_entries(monkeypatch,tmp_path):
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    save_style_library({'presets':{'Keep':asdict(CaptionStyle())},'recent':['#123456']})
    remember_font('Impact');remember_font('Arial');remember_font('Impact',True)
    prefs=load_style_library()
    assert prefs['recent_fonts']==['Arial','Impact'] and prefs['favourite_fonts']==['Impact']
    assert prefs['recent']==['#123456'] and 'Keep' in prefs['presets']
    names=('Arial','Impact','Segoe UI')
    assert font_rows(names,'','Unavailable',prefs)==['Arial','Impact','Segoe UI']
    assert font_rows(names,'IM','Arial',prefs)==['Impact']
    remember_font('Impact',True)
    assert load_style_library()['favourite_fonts']==[]


def test_whole_text_style_roundtrip_and_legacy_defaults():
    styled=TextOverlay(True,'Hello',style=CaptionStyle(font_size=64,colour='#FFD83D',italic=True))
    assert decode(encode(styled))==styled
    legacy=encode(TextOverlay(True,'Old text'));del legacy['values']['style']
    assert decode(legacy).style is None
    assert decode(legacy)==TextOverlay(True,'Old text')


def test_plain_and_timed_text_share_existing_colour_renderer(tmp_path):
    style=CaptionStyle(font_size=64,colour='#123456',outline_colour='#654321',underline=True,animation='none')
    plain=TextOverlay(True,'Same text',style=style)
    timed=TextOverlay(captions=(Caption(0,86400,'Same text',style=style),))
    definitions=[]
    for text in (plain,timed):
        with TextResources(text) as resources:
            filters=text_filter(1080,1920,text,resources,source_position=1)
            assert 'ass=filename' in filters
            definitions.append(next(Path(resources.temp.name).glob('style-*.ass')).read_text(encoding='utf-8'))
    assert definitions[0]==definitions[1]
    with TextResources(TextOverlay(True,'Legacy')) as resources:
        assert 'drawtext=' in text_filter(640,360,TextOverlay(True,'Legacy'),resources)


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS')=='1','Opt-in Windows Tk')
class TextStyleUITests(unittest.TestCase):
    pump=fixture.PulsePlanUITests.pump

    def setUp(self):
        gc.collect();fixture.PulsePlanUITests.setUp(self)
        self.environment=patch.dict(os.environ,LOCALAPPDATA=str(self.folder/'settings'))
        self.environment.start()

    def cleanup(self):
        for child in self.window.winfo_children():
            if isinstance(child,(CaptionDialog,TextStyleDialog)):
                worker=child.preview.worker;child.destroy();worker._thread.join(15)
        fixture.PulsePlanUITests.cleanup(self)
        self.environment.stop();self.window=self.root=None;gc.collect()

    def test_caption_controls_preview_drafts_and_advanced(self):
        w=self.window;dialog=CaptionDialog(w)
        dialog.geometry('840x620');self.root.update()
        self.assertFalse(dialog.styles.advanced.winfo_ismapped())
        for button in dialog.actions:
            self.assertTrue(button.winfo_ismapped())
            self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),dialog.winfo_rooty()+dialog.winfo_height())
        dialog.input.insert('1.0','Readable caption');dialog.start.set('1');dialog.end.set('3')
        style=dialog.styles
        style.variables['font_size'].set('64');style.choose_colour('colour','#FFD83D')
        style.variables['italic'].set(True);style.variables['underline'].set(True)
        style.location.set('Top right');style.choose_position()
        style.outline.set('Thick');style.choose_outline();style.shadow.set('Heavy');style.choose_shadow()
        self.assertEqual((style.read_style().outline,style.read_style().shadow_x),(6,10))
        self.pump(lambda:dialog.preview.photo is not None)
        self.assertEqual(w.edits.text.captions,())  # Draft preview never inserts a cue.
        dialog.save(False);self.assertEqual(len(w.edits.text.captions),1)
        original=w.edits.text.captions[0]
        self.assertEqual((original.start,original.end,original.position),(1,3,'Top'))
        dialog.input.delete('1.0','end');dialog.input.insert('1.0','Unsaved wording')
        style.variables['bold'].set(False)
        self.pump(lambda:not w.edits.text.captions[0].style.bold)
        self.assertEqual(dialog.input.get('1.0','end-1c'),'Unsaved wording')
        self.assertEqual(w.edits.text.captions[0].text,'Readable caption')
        style.toggle_advanced();self.root.update();self.assertTrue(style.advanced.winfo_ismapped())
        style.opacity.set('35%');style.set_opacity();self.assertEqual(style.read_style().background_opacity,.35)
        style.variables['font_size'].set('bad');dialog.save(True)
        self.assertEqual(w.edits.text.captions[0].text,'Readable caption')
        style.variables['font_size'].set('67');dialog.save(True)
        self.assertEqual(w.edits.text.captions[0].text,'Unsaved wording')
        self.assertEqual((w.edits.text.captions[0].start,w.edits.text.captions[0].end),(1,3))
        with patch('editor.style_controls.simpledialog.askstring',return_value='My style'):style.save_preset()
        style.variables['font_size'].set('88');style.preset.set('My style');style.choose_preset()
        self.assertEqual(style.read_style().font_size,67)
        dialog.new_caption();style.variables['font_size'].set('72');self.root.update()
        self.assertEqual(w.edits.text.captions[0].style.font_size,67)

    def test_visual_font_picker_search_keyboard_and_virtual_rows(self):
        picked=[]
        names=['Arial','Impact','Wingdings']+[f'Fixture {i}' for i in range(2000)]
        with patch('editor.font_picker.installed_fonts',return_value={n:() for n in names}):
            picker=FontPicker(self.window,'Arial',picked.append)
            self.pump(lambda:bool(picker.names))
            self.assertLess(len(picker.canvas.find_all()),90)
            picker.query.set('impa');self.root.update()
            self.assertEqual(picker.rows,['Impact'])
            # The visible sample actually uses its own family, not a Combobox row.
            fonts=[picker.canvas.itemcget(i,'font') for i in picker.canvas.find_all() if picker.canvas.type(i)=='text']
            self.assertTrue(any('Impact' in font for font in fonts))
            picker.accept();self.assertEqual(picked,['Impact'])
            self.assertEqual(load_style_library()['recent_fonts'][0],'Impact')

    def test_external_timeline_change_cannot_be_overwritten(self):
        w=self.window
        old=Caption(.5,2,'Original',style=CaptionStyle())
        w.edits=replace(w.edits,text=replace(w.edits.text,captions=(old,)))
        dialog=CaptionDialog(w);dialog.rows.selection_set(0);dialog.select()
        moved=replace(old,start=1,end=3)
        w.edits=replace(w.edits,text=replace(w.edits.text,captions=(moved,)))
        dialog.save(True)
        self.assertEqual(w.edits.text.captions,(moved,))
        self.assertIn('timeline changed',dialog.note.cget('text'))
        dialog.remove()
        self.assertEqual(w.edits.text.captions,(moved,))
        with self.assertRaisesRegex(ValueError,'timeline changed'):dialog.preview_draft()

    def test_whole_text_uses_same_controls_and_preserves_captions(self):
        w=self.window
        caption=Caption(.5,2,'Keep timing',style=CaptionStyle())
        w.edits=replace(w.edits,text=TextOverlay(True,'Whole clip',captions=(caption,)))
        w.overlay_tools.text_on.set(True);w.overlay_tools.input.insert('1.0','Whole clip')
        w.overlay_tools.input.edit_modified(False)
        dialog=TextStyleDialog(w)
        self.assertIsInstance(dialog.styles,StyleControls)
        self.assertIsNone(dialog.styles.read_style())
        dialog.styles.variables['font_family'].set('Impact');dialog.styles.variables['font_size'].set('72')
        dialog.styles.choose_colour('colour','#FF4466')
        self.pump(lambda:dialog.preview.photo is not None)
        self.assertIsNone(w.edits.text.style)
        dialog.apply()
        self.assertEqual(w.edits.text.style.font_family,'Impact')
        self.assertEqual(w.edits.text.style.colour,'#FF4466')
        self.assertEqual(w.edits.text.captions,(caption,))
        w.commit_entries();self.assertEqual(w.edits.text.style.font_size,72)
        self.assertEqual(decode(encode(w.edits)),w.edits)
        w.overlay_tools.text_size.set('Large');w.overlay_tools.size_changed()
        self.assertEqual(w.edits.text.style.font_size,97)


if __name__=='__main__':unittest.main()
