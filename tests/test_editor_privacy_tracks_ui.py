"""Timed privacy workflows in the real Tk editor."""
from dataclasses import replace
import os
import unittest
from unittest.mock import patch
from editor.cuts import CutPlan, CutRange
from editor.models import TrimRange
from editor.polish import Zoom, Fade
from editor.privacy import Rect, Privacy, PrivacyMask
from tests import test_editor_ui as fixtures


@unittest.skipUnless(os.environ.get('PULSE_RUN_UI_TESTS')=='1','Opt-in Windows Tk integration')
class PrivacyTrackUITests(unittest.TestCase):
    setUp=fixtures.EditorUITests.setUp
    cleanup_ui=fixtures.EditorUITests.cleanup_ui
    pump_until=fixtures.EditorUITests.pump_until
    next_picture=fixtures.EditorUITests.next_picture

    def add(self,start=.5,end=2,mode='Blur',rect=Rect(100,100,100,80)):
        w=self.window;c=w.overlay_tools
        self.next_picture(lambda:w.select_tool('PRIVACY'))
        c.new_mask()
        c.privacy_start.set(str(start));c.privacy_end.set(str(end));c.privacy_mode.set(mode)
        c.mask_changed(rect)
        self.next_picture(c.add_button.invoke)
        return c

    def choose(self,index):
        c=self.window.overlay_tools
        c.mask_list.selection_clear(0,'end');c.mask_list.selection_set(index)
        self.next_picture(c.select_mask)

    def test_add_select_update_remove_clear_and_stable_order(self):
        w=self.window;c=self.add()
        first=w.edits.privacy.masks[0]
        self.add(1,3,'Pixelate',Rect(150,120,120,100))
        self.assertEqual(c.mask_list.size(),2)
        self.choose(0)
        self.assertEqual(c.draft_rect,first.rect)
        self.assertEqual(c.privacy_mode.get(),'Blur')
        c.privacy_end.set('2.5')
        self.next_picture(lambda:c.mask_changed(Rect(120,130,100,80)))
        self.assertEqual(w.edits.privacy.masks[0],first)
        self.assertEqual(len(w.edits.privacy.masks),2)
        self.next_picture(c.update_button.invoke)
        self.assertEqual(w.edits.privacy.masks[0].end,2.5)
        self.assertEqual(w.edits.privacy.masks[1].mode,'Pixelate')
        self.next_picture(c.remove_button.invoke)
        self.assertEqual(len(w.edits.privacy.masks),1)
        self.assertEqual(w.edits.privacy.masks[0].mode,'Pixelate')
        self.next_picture(c.clear_button.invoke)
        self.assertEqual(w.edits.privacy.masks,())
        self.assertEqual(c.mask_list.size(),0)

    def test_playhead_times_and_scrub_active_masks(self):
        w=self.window;c=self.add(.5,2)
        self.add(1,3,'Pixelate',Rect(220,120,100,100))
        for position,expected in ((0,0),(.75,1),(1.5,2),(2.5,1),(3,0)):
            self.next_picture(lambda p=position:w.seek(p))
            self.assertEqual(len(w.video.active_masks),expected)
        self.next_picture(c.new_button.invoke)
        self.next_picture(lambda:w.seek(.7));c.privacy_use_playhead('start')
        self.next_picture(lambda:w.seek(2.7));c.privacy_use_playhead('end')
        c.mask_changed(Rect(50,50,100,100));self.next_picture(c.add_button.invoke)
        self.assertAlmostEqual(w.edits.privacy.masks[-1].start,.7)
        self.assertAlmostEqual(w.edits.privacy.masks[-1].end,2.7)
        self.assertEqual(len(w.timeline.find_withtag('privacy-range')),3)

    def test_invalid_draft_cannot_export_and_update_never_duplicates(self):
        w=self.window;c=self.add()
        original=w.edits.privacy
        c.privacy_start.set('3');c.privacy_end.set('2')
        c.update_button.invoke()
        self.assertEqual(w.edits.privacy,original)
        self.assertIn('after',w.note.cget('text'))
        w.export()
        self.assertFalse(w.exporter.busy)
        self.assertIn('draft',w.note.cget('text'))
        c.privacy_start.set('.5')  # parser intentionally requires a leading digit
        c.update_button.invoke()
        self.assertEqual(w.edits.privacy,original)
        c.privacy_start.set('0.5');c.privacy_end.set('3')
        self.next_picture(c.update_button.invoke)
        self.assertEqual(len(w.edits.privacy.masks),1)
        self.assertFalse(c.dirty())

    def test_crop_zoom_and_tool_switch_preserve_selection_and_masks(self):
        w=self.window;c=self.add(0,4,rect=Rect(100,100,100,100))
        self.add(1,3,'Pixelate',Rect(240,140,100,100))
        self.choose(0)
        saved=w.edits.privacy
        w.edits=replace(w.edits,zoom=Zoom(True,2),fade=Fade(True,True))
        w.format_choice.set('9:16 Vertical');self.next_picture(w.format_changed)
        self.next_picture(lambda:w.seek(1.5))
        self.assertFalse(w.video.display_zoomed)
        self.assertTrue(w.video.ready())
        self.assertEqual(len(w.video.active_masks),2)
        self.assertTrue(w.video.find_withtag('privacy-active'))
        for tool in ('FORMAT','CROP','PRIVACY'):
            self.next_picture(lambda t=tool:w.select_tool(t))
            self.assertEqual(c.selected,0)
            self.assertEqual(w.edits.privacy,saved)
        self.assertTrue(w.edits.zoom.enabled)
        self.assertEqual(w.edits.fade,Fade(True,True))
        w.update_trim(TrimRange(2,4))
        self.assertEqual(w.edits.privacy,saved)

    def test_cut_playback_skips_removed_mask_times(self):
        w=self.window;c=self.add(.5,1)
        self.add(2,3,'Pixelate')
        w.cuts=CutPlan((CutRange(1,2),))
        w.cuts_changed('Test cuts')
        self.next_picture(lambda:w.seek(.75))
        w.play_preview()
        with patch('editor.editor_window.time.monotonic',return_value=w.play_started+.5):
            self.next_picture(w.next_frame)
        self.assertAlmostEqual(w.position,2.25)
        self.assertEqual([m.mode for _,m in w.video.active_masks],['Pixelate'])
        w.pause_preview();w.stop_preview()
        self.assertEqual(w.position,0)
        self.assertEqual(len(w.cuts.ranges),1)

    def test_minimum_layout_busy_state_and_scrollable_list(self):
        w=self.window;c=self.add()
        for i in range(6):
            self.add(0,4,'Pixelate' if i%2 else 'Blur')
        w.geometry('760x700');self.root.update()
        def inspect(parent):
            for child in parent.winfo_children():
                if child.winfo_ismapped():
                    self.assertGreaterEqual(child.winfo_height(),child.winfo_reqheight(),str(child))
                    self.assertGreaterEqual(child.winfo_width(),child.winfo_reqwidth(),str(child))
                    self.assertLessEqual(child.winfo_y()+child.winfo_height(),parent.winfo_height()+1)
                    self.assertLessEqual(child.winfo_x()+child.winfo_width(),parent.winfo_width()+1)
                    inspect(child)
        inspect(w.panels['PRIVACY'])
        self.assertGreater(w.video.winfo_height(),120)
        self.assertGreaterEqual(w.timeline.winfo_height(),65)
        c.mask_list.yview_moveto(1);self.root.update()
        self.assertGreater(c.mask_list.yview()[0],0)
        self.choose(0)
        edits=w.edits
        w.set_busy(True)
        for b in (c.add_button,c.update_button,c.remove_button,c.clear_button,c.new_button,c.mask_list):
            self.assertEqual(str(b['state']),'disabled')
        c.mask_changed(Rect(0,0,20,20));c.add_mask();c.update_mask();c.remove_mask();c.clear_masks()
        self.assertEqual(w.edits,edits)
        w.set_busy(False)
        self.assertEqual(str(c.update_button['state']),'normal')

    def test_selecting_fractional_frame_times_does_not_change_mask(self):
        w=self.window;c=w.overlay_tools
        mask=PrivacyMask('Blur',Rect(100,100,100,80),1/30,2+1/30)
        w.edits=replace(w.edits,privacy=Privacy((mask,)))
        self.next_picture(lambda:w.select_tool('PRIVACY'))
        self.choose(0)
        self.assertFalse(c.dirty())
        self.next_picture(c.update_button.invoke)
        self.assertEqual(w.edits.privacy.masks,(mask,))
        w.media=replace(w.media,duration=4.0006)
        w.update_trim(TrimRange(0,w.media.duration))
        c.new_mask();c.mask_changed(mask.rect)
        self.next_picture(c.add_button.invoke)
        self.assertEqual(w.edits.privacy.masks[-1].end,w.media.duration)
