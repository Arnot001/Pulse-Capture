"""Whole-clip text styling uses the same controls and renderer as timed captions."""
from dataclasses import replace
import tkinter as tk
from ui import theme as t
from .style_controls import StyleControls, scrollable_styles
from .style_preview import StylePreview
from .style_preferences import save_caption_preference
from .typography import CaptionStyle
from .text_overlay import TEXT_SIZES
from .edit_history import EditHistory, EditSnapshot


class TextStyleDialog(tk.Toplevel):
    def __init__(self,window):
        super().__init__(window)
        self.window=window;self.title('Text / style');self.configure(bg=t.BG);self.transient(window)
        self.geometry(f'{min(900,self.winfo_screenwidth()-60)}x{min(640,self.winfo_screenheight()-90)}')
        self.minsize(800,540)
        footer=tk.Frame(self,bg=t.BG);footer.pack(side='bottom',fill='x',padx=14,pady=10)
        self.note=t.label(footer,'Whole-clip text · Preview changes, then Apply style.',9,t.MUTED,wraplength=820)
        self.note.pack(fill='x',pady=(0,6))
        t.button(footer,'APPLY STYLE',self.apply,accent=True).pack(side='left',fill='x',expand=True)
        t.button(footer,'DONE',self.destroy).pack(side='right',padx=(8,0))
        body=tk.Frame(self,bg=t.BG);body.pack(fill='both',expand=True,padx=14,pady=10)
        body.columnconfigure(0,weight=2,minsize=280);body.columnconfigure(1,weight=3,minsize=440);body.rowconfigure(0,weight=1)
        left=tk.Frame(body,bg=t.BG);left.grid(row=0,column=0,sticky='nsew',padx=(0,14))
        self.preview=StylePreview(left,window,self.preview_draft);self.preview.pack(fill='both',expand=True)
        self.preview.bind('<B1-Motion>',self.drag)
        t.label(left,'Drag the preview to position text',9,t.MUTED).pack(anchor='w',pady=4)
        self.input=tk.Text(left,height=3,wrap='word',bg=t.CONTROL,fg=t.TEXT,insertbackground=t.CYAN,undo=True)
        self.input.pack(fill='x',pady=4);self.input.insert('1.0',window.edits.text.text)
        self.input.bind('<KeyRelease>',lambda _:self.preview.refresh())
        self.position=tk.StringVar(value=window.edits.text.position)
        panel,inner=scrollable_styles(body);panel.grid(row=0,column=1,sticky='nsew')
        initial=window.edits.text.style or CaptionStyle(font_family='Segoe UI',font_size=round(TEXT_SIZES[window.edits.text.size]*1080),
            bold=False,outline=0,shadow=0,animation='none',background_enabled=True)
        self.styles=StyleControls(inner,self.position,self.preview.refresh,initial,bool(window.edits.comedy_bands))
        self.styles.pack(fill='x')
        if window.edits.text.style is None:self.styles.enabled.set(False)
        self.preview.refresh();self.protocol('WM_DELETE_WINDOW',self.destroy)

    def draft_text(self):
        return replace(self.window.edits.text,text=self.input.get('1.0','end-1c'),
                       position=self.position.get(),style=self.styles.read_style())

    def preview_draft(self):
        text=self.draft_text()
        text=replace(text,enabled=True,text=text.text.strip() or 'YOUR TEXT')
        return replace(self.window.edits,text=text),self.window.position

    def drag(self,event):
        point=self.preview.point(event)
        if not point:return
        x,y=point
        if self.window.edits.comedy_bands:
            zone='Top' if y<.5 else 'Bottom';self.position.set(zone)
            band=self.window.edits.bands(self.window.media)[zone.lower()]
            _,height=self.window.edits.encoded_size(self.window.media)
            self.styles.variables['band_y'].set(max(0,min(1,(y*height-band.y)/band.height)))
        else:
            self.position.set('Centre');self.styles.variables['alignment'].set('centre')
            self.styles.variables['x_offset'].set(f'{max(-.4,min(.4,x-.5)):.3f}')
            self.styles.variables['y_offset'].set(f'{max(-.4,min(.4,y-.5)):.3f}')

    def apply(self):
        w=self.window
        try:
            if w.closing or w.exporter.busy:raise ValueError('Wait for export to finish.')
            text=self.draft_text()
            # Apply styling preserves the ON/OFF state and all timed captions.
            edits=replace(w.edits,text=text);edits.validate(w.media)
            before=EditSnapshot(w.trim,w.cuts,w.edits)
            if w.timeline_history is None or w.timeline_history.current!=before:w.timeline_history=EditHistory(before)
            w.stop_play();w.edits=edits;w.timeline_history.record(EditSnapshot(w.trim,w.cuts,edits))
            tools=w.overlay_tools
            tools.input.delete('1.0','end');tools.input.insert('1.0',text.text)
            tools.input.edit_modified(False);tools.text_position.set(text.position)
            w.update_timeline();w.request_frame();save_caption_preference(text.style)
            self.note.configure(text='Style applied to whole-clip text. Caption text and timings are unchanged.',fg=t.GREEN)
        except (ValueError,tk.TclError) as exc:self.note.configure(text=str(exc),fg=t.RED)

    def destroy(self):
        self.preview.close();super().destroy()
