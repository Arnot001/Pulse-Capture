"""Beginner-friendly Motion and Finish controls for Quick Edit."""
from dataclasses import replace
import tkinter as tk
from ui import theme as t
from .polish import Fade, Zoom, SPEEDS, ZOOM_FACTORS
from .transforms import Branding


class PolishTools:
    def __init__(self, window):
        self.window = window
        self.zoom_on = tk.BooleanVar(value=False)
        self.zoom_factor = tk.StringVar(value='1.5x')
        self.speed = tk.StringVar(value='1.0x')
        self.fade_in = tk.BooleanVar(value=False)
        self.fade_out = tk.BooleanVar(value=False)

        panel = window.panels['MOTION']
        row = tk.Frame(panel, bg=t.PANEL)
        row.pack(fill='x')
        zoom_toggle = tk.Frame(row, bg=t.PANEL)
        zoom_toggle.pack(side='left', padx=(0, 10))
        window.add_segments(zoom_toggle, self.zoom_on, [(False, 'ZOOM OFF'), (True, 'ZOOM ON')], self.motion_changed)
        zoom_amount = tk.Frame(row, bg=t.PANEL)
        zoom_amount.pack(side='left', fill='x', expand=True)
        window.add_segments(zoom_amount, self.zoom_factor,
                            [(f'{v:g}x', f'{v:g}x') for v in ZOOM_FACTORS], self.motion_changed)

        speed_row = tk.Frame(panel, bg=t.PANEL)
        speed_row.pack(fill='x', pady=(3, 0))
        t.label(speed_row, 'SPEED', 9, t.MUTED, True).pack(side='left', padx=(0, 8))
        speed_group = tk.Frame(speed_row, bg=t.PANEL)
        speed_group.pack(side='left', fill='x', expand=True)
        speed_choices = [('0.5x', '0.5x'), ('1.0x', '1.0x'), ('1.5x', '1.5x'), ('2.0x', '2.0x')]
        window.add_segments(speed_group, self.speed, speed_choices, self.motion_changed)
        self.motion_hint = t.label(panel, 'Turn Zoom on, then click or drag on the preview to choose the focus.',
                                   9, t.MUTED)
        self.motion_hint.pack(anchor='w', pady=(3, 0))

        panel = window.panels['FINISH']
        row = tk.Frame(panel, bg=t.PANEL)
        row.pack(fill='x')
        left = tk.Frame(row, bg=t.PANEL)
        left.pack(side='left', fill='x', expand=True, padx=(0, 8))
        window.add_segments(left, self.fade_in, [(False, 'FADE IN OFF'), (True, 'FADE IN ON')], self.finish_changed)
        right = tk.Frame(row, bg=t.PANEL)
        right.pack(side='left', fill='x', expand=True, padx=(0, 8))
        window.add_segments(right, self.fade_out, [(False, 'FADE OUT OFF'), (True, 'FADE OUT ON')], self.finish_changed)
        promo = t.button(row, '⚡  PULSE PROMO', self.apply_promo, accent=True)
        promo.pack(side='right')
        window.controls.append(promo)
        t.label(panel, 'Promo: Vertical · Pulse brand · clean fades · keeps your trim, text and privacy.',
                9, t.MUTED).pack(anchor='w', pady=(6, 0))

    @staticmethod
    def _number(value):
        return float(str(value).lower().rstrip('x'))

    def motion_changed(self):
        w = self.window
        if w.exporter.busy or w.closing:
            return
        try:
            zoom = replace(w.edits.zoom, enabled=self.zoom_on.get(),
                           factor=self._number(self.zoom_factor.get()))
            speed = self._number(self.speed.get())
            w.edits = replace(w.edits, zoom=zoom, speed=speed)
            if w.media:
                w.edits.validate(w.media)
            w.stop_play()
            self.refresh()
            w.request_frame()
        except ValueError as exc:
            w.note.configure(text=str(exc), fg=t.RED)

    def finish_changed(self):
        w = self.window
        if w.exporter.busy or w.closing:
            return
        w.edits = replace(w.edits, fade=Fade(self.fade_in.get(), self.fade_out.get()))
        if w.media:
            try:
                w.edits.validate(w.media)
            except ValueError as exc:
                w.note.configure(text=str(exc), fg=t.RED)
                return
        w.stop_play()
        w.request_frame()

    def focus_changed(self, focus_x, focus_y):
        w = self.window
        if w.exporter.busy or w.closing or not self.zoom_on.get():
            return
        w.edits = replace(w.edits, zoom=replace(w.edits.zoom, enabled=True,
                                                focus_x=focus_x, focus_y=focus_y))
        self.refresh()
        w.request_frame()

    def apply_promo(self):
        w = self.window
        if not w.media or w.exporter.busy or w.closing:
            return
        try:
            edits = w.edits.with_format(w.media, '9:16 Vertical')
            edits = replace(edits,
                            branding=Branding(True, 'Bottom right', 'Medium'),
                            zoom=replace(edits.zoom, enabled=False),
                            speed=1.0,
                            fade=Fade(True, True))
            edits.validate(w.media)
            w.edits = edits
            w.format_choice.set(edits.preset)
            w.brand_on.set(True)
            w.brand_corner.set('Bottom right')
            w.brand_size.set('Medium')
            self.sync()
            w.video.crop = edits.crop
            w.overlay_tools.refresh()
            w.update_brand_controls()
            w.stop_play()
            self.refresh()
            w.note.configure(text='PULSE PROMO applied · your trim, text and privacy were kept.', fg=t.CYAN)
            w.request_frame()
        except ValueError as exc:
            w.note.configure(text=str(exc), fg=t.RED)

    def sync(self):
        w = self.window
        self.zoom_on.set(w.edits.zoom.enabled)
        self.zoom_factor.set(f'{w.edits.zoom.factor:g}x')
        self.speed.set('1.0x' if w.edits.speed == 1.0 else f'{w.edits.speed:g}x')
        self.fade_in.set(w.edits.fade.fade_in)
        self.fade_out.set(w.edits.fade.fade_out)

    def refresh(self):
        w = self.window
        if not hasattr(w, 'video'):
            return
        w.video.zoom_active = w.tool.get() == 'MOTION' and w.edits.zoom.enabled
        w.video.zoom_focus = (w.edits.zoom.focus_x, w.edits.zoom.focus_y)
        w.video.draw_overlay()
