"""Beginner-friendly Motion and Finish controls for Quick Edit."""
from dataclasses import replace
import tkinter as tk
from ui import theme as t
from .polish import Fade, Zoom, SPEEDS, ZOOM_FACTORS, ZOOM_MODES, ZOOM_TIMINGS
from .transforms import Branding


class PolishTools:
    def __init__(self, window):
        self.window = window
        # Preview-only state: never stored in EditOptions or used by export.
        self.zoom_result = False
        self.zoom_on = tk.BooleanVar(value=False)
        self.zoom_factor = tk.StringVar(value='1.5x')
        self.zoom_mode = tk.StringVar(value='Static')
        self.zoom_motion = tk.StringVar(value='Medium')
        self.speed = tk.StringVar(value='1.0x')
        self.fade_in = tk.BooleanVar(value=False)
        self.fade_out = tk.BooleanVar(value=False)

        panel = window.panels['MOTION']
        def row():
            frame = tk.Frame(panel, bg=t.PANEL)
            frame.pack(fill='x', pady=(0, 2))
            return frame

        def segments(parent, variable, choices):
            group = t.Segments(parent, variable, choices, self.motion_changed)
            group.pack(side='left', fill='x', expand=True, padx=(0, 6))
            for _, button in group.buttons:
                button.configure(padx=7, pady=2, font=(t.FONT, -12, 'bold'))
                window.controls.append(button)
            return group

        zoom_row = row()
        segments(zoom_row, self.zoom_on, [(False, 'ZOOM OFF'), (True, 'ZOOM ON')])
        segments(zoom_row, self.zoom_factor, [(f'{v:g}x', f'{v:g}x') for v in ZOOM_FACTORS])
        mode_row = row()
        self.mode_segments = segments(mode_row, self.zoom_mode, [(v, v.upper()) for v in ZOOM_MODES])
        t.label(mode_row, 'ZOOM MOTION', 8, t.MUTED, True).pack(side='left', padx=(4, 8))
        self.motion_segments = segments(mode_row, self.zoom_motion, [(v, v.upper()) for v in ZOOM_TIMINGS])
        speed_row = row()
        t.label(speed_row, 'CLIP SPEED', 8, t.MUTED, True).pack(side='left', padx=(0, 8))
        self.speed_segments = segments(speed_row, self.speed, [(f'{v:.1f}x', f'{v:.1f}x') for v in SPEEDS])
        preview_row = row()
        self.zoom_view_button = t.button(preview_row, 'VIEW ZOOM RESULT', self.toggle_zoom_view,
                                         accent=True, font=(t.FONT, -12, 'bold'))
        self.zoom_view_button.configure(pady=2, state='disabled')
        self.zoom_view_button.pack(side='left', padx=(0, 10))
        window.controls.append(self.zoom_view_button)
        self.motion_hint = t.label(preview_row, 'Turn Zoom on to choose the focus.', 9, t.MUTED)
        self.motion_hint.pack(side='left')

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
                           factor=self._number(self.zoom_factor.get()),
                           mode=self.zoom_mode.get(), motion_speed=self.zoom_motion.get())
            speed = self._number(self.speed.get())
            w.stop_play()
            w.edits = replace(w.edits, zoom=zoom, speed=speed)
            if w.media:
                w.edits.validate(w.media)
            self.refresh()
            w.request_frame()
        except ValueError as exc:
            w.note.configure(text=str(exc), fg=t.RED)

    def toggle_zoom_view(self):
        w = self.window
        if (not w.media or w.exporter.busy or w.closing or
                w.tool.get() != 'MOTION' or not w.edits.zoom.enabled):
            return
        w.stop_play()
        self.zoom_result = not self.zoom_result
        w.video.zoom_drag = False
        self.refresh()
        if self.zoom_result and w.edits.zoom.mode == 'Zoom in':
            w.position = w.trim.start
            w.play_preview()
        else:
            w.request_frame()

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
        if (w.exporter.busy or w.closing or not w.edits.zoom.enabled or
                self.zoom_result or w.tool.get() != 'MOTION'):
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
        self.zoom_mode.set(w.edits.zoom.mode)
        self.zoom_motion.set(w.edits.zoom.motion_speed)
        self.speed.set(f'{w.edits.speed:.1f}x')
        self.fade_in.set(w.edits.fade.fade_in)
        self.fade_out.set(w.edits.fade.fade_out)

    def refresh(self):
        w = self.window
        if not hasattr(w, 'video'):
            return
        if not w.edits.zoom.enabled:
            self.zoom_result = False
        ready = bool(w.media and w.video.enabled and not w.exporter.busy and not w.closing)
        self.mode_segments.enable(ready and w.edits.zoom.enabled)
        self.motion_segments.enable(ready and w.edits.zoom.enabled and w.edits.zoom.mode == 'Zoom in')
        self.zoom_view_button.configure(
            text='EDIT ZOOM FOCUS' if self.zoom_result else 'VIEW ZOOM RESULT',
            state='normal' if ready and w.edits.zoom.enabled else 'disabled')
        self.motion_hint.configure(text=(
            'Turn Zoom on to choose the focus.' if not w.edits.zoom.enabled else
            'Play or scrub to preview the zoom motion.' if self.zoom_result and w.edits.zoom.mode == 'Zoom in' else
            'Showing your zoomed result.' if self.zoom_result else
            'Click or drag the cyan target to choose the focus.'))
        w.video.zoom_active = (w.tool.get() == 'MOTION' and w.edits.zoom.enabled
                               and not self.zoom_result)
        if not w.video.zoom_active:
            w.video.zoom_drag = False
        w.video.zoom_focus = (w.edits.zoom.focus_x, w.edits.zoom.focus_y)
        w.video.draw_overlay()
