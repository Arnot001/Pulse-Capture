"""Screen 1: configure, capture, and save. All worker events cross a queue."""
import os
from pathlib import Path
from queue import Empty, Queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import settings
from branding import asset_root, watermark_path
from capture.audio_devices import AudioInventory, discover_audio
from capture.ffmpeg_backend import discover
from capture.hotkey import GlobalHotkey
from capture.models import CaptureOptions
from capture.recorder import Recorder, State
from capture.window_picker import list_windows, validate_window
from .region_overlay import RegionOverlay
from . import theme as t


def choose_quick_edit_path(parent, last_file, output_folder):
    """Use the latest recording when available; otherwise let the user choose an MP4."""
    if last_file:
        latest = Path(last_file)
        if latest.is_file():
            return latest
    selected = filedialog.askopenfilename(
        parent=parent,
        initialdir=str(output_folder),
        title='Choose a video to edit',
        filetypes=(('MP4 video', '*.mp4'), ('All files', '*.*')),
    )
    return Path(selected) if selected else None


class CaptureApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self._destroyed = False
        self.title('PULSE // CAPTURE')
        height = min(900, self.winfo_screenheight() - 90)
        self.geometry(f'650x{height}')
        self.minsize(570, 660)
        t.install(self)
        self.asset_root = asset_root()
        icon = self.asset_root / 'assets' / 'branding' / 'pulse.ico'
        self.watermark_asset = watermark_path()
        if icon.is_file():
            self.iconbitmap(str(icon))
        self.prefs = settings.load()
        self.backend = self.recorder = None
        self.inventory = AudioInventory()
        self.discoveries = Queue()
        self.detecting = False
        self.windows, self.region = [], None
        self.last_file = None
        self.editors = set()
        self.closing = False
        self.hotkey = GlobalHotkey()
        self.mode = tk.StringVar(value='screen')
        self.fps = tk.IntVar(value=self.prefs.fps)
        self.quality = tk.StringVar(value=self.prefs.quality)
        self.mic_on = tk.BooleanVar(value=self.prefs.microphone)
        self.system_on = tk.BooleanVar(value=self.prefs.system_audio)
        self.hotkey_on = tk.BooleanVar(value=self.prefs.hotkey)
        self.watermark_on = tk.BooleanVar(value=self.prefs.watermark)
        self.watermark_position = tk.StringVar(value=self.prefs.watermark_position)
        self._shell()
        self._screen()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self._poll_id = self.after(100, self.poll)
        self.after(150, self.refresh_devices)
        if self.hotkey_on.get():
            self.after(200, self.set_hotkey)

    def _shell(self):
        stripe = tk.Canvas(self, height=3, bg=t.BG, highlightthickness=0)
        stripe.pack(fill='x')
        stripe.bind('<Configure>', lambda e: (stripe.delete('all'), stripe.create_rectangle(
            0, 0, e.width * .72, 3, outline='', fill=t.CYAN)))
        header = tk.Frame(self, bg=t.BG)
        header.pack(fill='x', padx=26, pady=(16, 12))
        t.label(header, 'PULSE', 24, t.TEXT, True).pack(side='left')
        t.label(header, ' // CAPTURE', 17, t.CYAN).pack(side='left', pady=(5, 0))
        self.status = t.label(header, '● CHECKING', 9, t.MUTED, True)
        self.status.pack(side='right', pady=(7, 0))
        # Scrollable shell remains usable on smaller/high-DPI displays.
        container = tk.Frame(self, bg=t.BG)
        container.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(container, bg=t.BG, highlightthickness=0)
        bar = ttk.Scrollbar(container, orient='vertical', command=self.canvas.yview)
        def scroll_position(first, last):
            bar.set(first, last)
            if float(first) <= 0 and float(last) >= 1:
                bar.pack_forget()
            else:
                bar.pack(side='right', fill='y', before=self.canvas)
        self.canvas.configure(yscrollcommand=scroll_position)
        bar.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.content = tk.Frame(self.canvas, bg=t.BG)
        item = self.canvas.create_window((0, 0), window=self.content, anchor='nw')
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(item, width=e.width))
        self.content.bind('<Configure>', lambda _: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind_all('<MouseWheel>', self._wheel, add='+')
        footer = tk.Frame(self, bg=t.BG)
        footer.pack(fill='x', padx=26, pady=(10, 8))
        t.label(footer, 'LOCAL CAPTURE.  NOTHING ELSE.', 8, t.MUTED, True).pack(side='left')
        t.label(footer, 'PULSE UTILITIES  /  v0.4.0', 8, t.MUTED).pack(side='right')

    def _wheel(self, event):
        if event.widget.winfo_toplevel() == self and not isinstance(event.widget, ttk.Combobox):
            self.canvas.yview_scroll(-int(event.delta / 120), 'units')

    def _screen(self):
        body = tk.Frame(self.content, bg=t.BG)
        body.pack(fill='x', padx=26)
        intro = tk.Frame(body, bg=t.BG)
        intro.pack(fill='x', pady=(0, 10))
        t.label(intro, 'Your screen. In motion.', 19, bold=True).pack(anchor='w')
        t.label(intro, 'Simple Windows screen recording. Saved straight to your PC.',
                10, t.MUTED).pack(anchor='w', pady=(4, 0))

        capture = t.Card(body, '01', 'CAPTURE SOURCE')
        capture.pack(fill='x', pady=(0, 10))
        self.capture_segments = t.Segments(capture.body, self.mode,
            [('screen', 'FULL SCREEN'), ('window', 'WINDOW'), ('region', 'AREA')], self.mode_changed)
        self.capture_segments.pack(fill='x')
        self.target_row = tk.Frame(capture.body, bg=t.PANEL)
        self.target_row.pack(fill='x', pady=(10, 0))
        self.target_text = t.label(self.target_row, 'Entire desktop  ·  Cursor included', 9, t.MUTED)
        self.target_text.pack(side='left')
        self.window_var = tk.StringVar()
        self.window_combo = ttk.Combobox(self.target_row, textvariable=self.window_var, state='readonly')
        self.target_button = t.button(self.target_row, 'SELECT', self.select_target)
        self.target_button.configure(pady=3)

        audio = t.Card(body, '02', 'AUDIO')
        audio.pack(fill='x', pady=(0, 10))
        self.mic_toggle, self.mic_combo = self.audio_row(audio.body, 'MIC / INPUT', self.mic_on)
        self.system_toggle, self.system_combo = self.audio_row(audio.body, 'SYSTEM AUDIO', self.system_on)
        self.audio_notice = t.label(audio.body, 'Checking available audio inputs…', 9, t.MUTED,
                                    anchor='w', justify='left', wraplength=495)
        self.audio_notice.pack(fill='x', pady=(5, 0))
        self.refresh_button = t.button(audio.body, '↻  REFRESH DEVICES', self.refresh_devices)
        self.refresh_button.configure(pady=4, font=(t.FONT, -11, 'bold'))
        self.refresh_button.pack(anchor='e', pady=(7, 0))

        quality = t.Card(body, '03', 'RECORDING QUALITY')
        quality.pack(fill='x', pady=(0, 10))
        row = quality.body
        self.quality_combo = ttk.Combobox(row, textvariable=self.quality,
                                         values=('Standard', 'High'), state='readonly', width=16)
        self.quality_combo.pack(side='left')
        self.fps_segments = t.Segments(row, self.fps, [(30, '30 FPS'), (60, '60 FPS')])
        self.fps_segments.pack(side='right')

        branding = t.Card(body, '04', 'BRANDING')
        branding.pack(fill='x', pady=(0, 10))
        brand_row = tk.Frame(branding.body, bg=t.PANEL)
        brand_row.pack(fill='x')
        t.label(brand_row, 'PULSE WATERMARK', 9, bold=True, anchor='w').pack(side='left')
        self.watermark_toggle = tk.Checkbutton(
            brand_row, text='ON', variable=self.watermark_on, command=self.watermark_changed,
            bg=t.PANEL, fg=t.CYAN, selectcolor=t.CONTROL, activebackground=t.PANEL,
            activeforeground=t.TEXT, disabledforeground=t.MUTED, bd=0)
        self.watermark_toggle.pack(side='right', padx=(8, 0))
        self.watermark_on.trace_add('write', lambda *_: self.watermark_toggle.configure(
            text='ON' if self.watermark_on.get() else 'OFF'))
        self.watermark_combo = ttk.Combobox(
            brand_row, textvariable=self.watermark_position,
            values=('Bottom right', 'Bottom left', 'Top right', 'Top left'),
            state='readonly', width=16)
        self.watermark_combo.pack(side='right', padx=(8, 0))
        self.watermark_note = t.label(
            branding.body, 'Optional · subtle Pulse logo burned into the saved MP4.',
            9, t.MUTED, anchor='w')
        self.watermark_note.pack(fill='x', pady=(6, 0))
        self.watermark_changed()

        self.record_button = t.button(body, '●   START RECORDING', self.toggle, accent=True,
                                       font=(t.FONT, -17, 'bold'))
        self.record_button.configure(pady=12, state='disabled')
        self.record_button.pack(fill='x')
        clockrow = tk.Frame(body, bg=t.BG)
        clockrow.pack(fill='x', pady=(8, 4))
        self.timer = tk.Label(clockrow, text='00:00:00', font=(t.MONO, -35), bg=t.BG, fg=t.TEXT)
        self.timer.pack()
        self.hint = t.label(clockrow, 'MP4  /  H.264  /  SAVED LOCALLY', 8, t.MUTED, True)
        self.hint.pack(pady=(2, 0))

        self.message = t.label(body, 'Checking recording engine…', 9, t.MUTED,
                               justify='left', anchor='w', wraplength=515)
        self.message.pack(fill='x', pady=(5, 8))
        actions = tk.Frame(body, bg=t.BG)
        actions.pack(fill='x', pady=(0, 10))
        self.quick_edit_button = t.button(actions, 'QUICK EDIT  →', self.open_quick_edit, accent=True)
        self.quick_edit_button.configure(state='disabled')
        self.quick_edit_button.pack(side='left', fill='x', expand=True, padx=(0, 10))
        t.button(actions, 'OPEN FOLDER ↗', self.open_folder).pack(side='right', fill='x', expand=True)
        destination = tk.Frame(body, bg=t.BG)
        destination.pack(fill='x')
        t.label(destination, 'SAVE TO', 8, t.CYAN, True).pack(anchor='w')
        self.folder_label = t.label(destination, str(self.prefs.output), 9, t.MUTED,
                                    wraplength=390, justify='left', anchor='w')
        self.folder_label.pack(side='left', fill='x', expand=True, pady=(3, 0))
        self.hotkey_check = tk.Checkbutton(body, text='Enable global shortcut  Ctrl + Shift + R',
            variable=self.hotkey_on, command=self.set_hotkey, bg=t.BG, fg=t.MUTED,
            selectcolor=t.CONTROL, activebackground=t.BG, activeforeground=t.TEXT, bd=0)
        self.hotkey_check.pack(anchor='w', pady=(12, 5))

    def audio_row(self, parent, title, variable):
        row = tk.Frame(parent, bg=t.PANEL)
        row.pack(fill='x', pady=3)
        t.label(row, title, 9, bold=True, width=14, anchor='w').pack(side='left')
        toggle = tk.Checkbutton(row, text='ON', variable=variable, bg=t.PANEL, fg=t.CYAN,
            selectcolor=t.CONTROL, activebackground=t.PANEL, activeforeground=t.TEXT,
            disabledforeground=t.MUTED, bd=0, state='disabled')
        toggle.pack(side='right', padx=(8, 0))
        variable.trace_add('write', lambda *_: toggle.configure(text='ON' if variable.get() else 'OFF'))
        combo = ttk.Combobox(row, state='disabled', width=25)
        combo.set('Checking…')
        combo.pack(side='left', fill='x', expand=True)
        return toggle, combo

    def watermark_changed(self):
        enabled = self.watermark_on.get() and self.watermark_asset.is_file()
        busy = bool(self.recorder and self.recorder.busy)
        self.watermark_combo.configure(state='readonly' if enabled and not busy else 'disabled')
        if self.watermark_on.get() and not self.watermark_asset.is_file():
            self.watermark_note.configure(text='Watermark unavailable · branding asset is missing.', fg=t.RED)
        else:
            self.watermark_note.configure(
                text='Optional · subtle Pulse logo burned into the saved MP4.', fg=t.MUTED)

    def mode_changed(self):
        self.target_text.pack_forget()
        self.window_combo.pack_forget()
        self.target_button.pack_forget()
        if self.mode.get() == 'window':
            self.window_combo.pack(side='left', fill='x', expand=True)
            self.target_button.configure(text='↻', command=self.refresh_windows)
            self.target_button.pack(side='right', padx=(8, 0))
            self.refresh_windows()
        else:
            self.target_text.pack(side='left')
            if self.mode.get() == 'region':
                self.target_text.configure(text=self.region_text())
                self.target_button.configure(text='SELECT AREA', command=self.pick_region)
                self.target_button.pack(side='right')
            else:
                self.target_text.configure(text='Entire desktop  ·  Cursor included')

    def select_target(self):
        self.pick_region() if self.mode.get() == 'region' else self.refresh_windows()

    def region_text(self):
        r = self.region
        return f'{r.width} × {r.height} px  ·  ({r.x}, {r.y})' if r else 'Drag a rectangle on your desktop'

    def refresh_windows(self):
        try:
            self.windows = list_windows()
            self.window_combo.configure(values=[f'{w.title}{" (minimized — restore first)" if w.minimized else ""}  [{w.hwnd}]' for w in self.windows])
            if self.windows:
                self.window_combo.current(0)
            else:
                self.window_combo.set('No visible windows')
        except Exception as exc:
            self.show_error(str(exc))

    def pick_region(self):
        self.withdraw()
        def picked(region):
            if region:
                self.region = region
            self.deiconify()
            self.target_text.configure(text=self.region_text())
        def open_overlay():
            try:
                RegionOverlay(self, picked)
            except Exception as exc:
                self.deiconify()
                self.show_error(str(exc))
        self.after(180, open_overlay)

    def refresh_devices(self):
        if self.detecting or (self.recorder and self.recorder.busy):
            return
        self.detecting = True
        self.record_button.configure(state='disabled')
        self.refresh_button.configure(state='disabled')
        self.status.configure(text='● CHECKING', fg=t.MUTED)
        def work():
            try:
                backend = discover()
                try:
                    inventory = discover_audio(backend)
                except Exception as exc:
                    inventory = AudioInventory(notice=f'Audio discovery failed: {exc}. Video capture is available.')
                self.discoveries.put((backend, inventory, None))
            except Exception as exc:
                self.discoveries.put((None, AudioInventory(), str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def apply_devices(self, backend, inventory, error):
        self.detecting = False
        self.backend, self.inventory = backend, inventory
        self.recorder = Recorder(backend) if backend else None
        for devices, combo, toggle, variable, preferred in (
            (inventory.microphones, self.mic_combo, self.mic_toggle, self.mic_on, self.prefs.mic_device),
            (inventory.loopbacks, self.system_combo, self.system_toggle, self.system_on, self.prefs.system_device)):
            combo.configure(values=[f'{i + 1}. {d.name}' for i, d in enumerate(devices)],
                            state='readonly' if devices else 'disabled')
            toggle.configure(state='normal' if devices else 'disabled')
            if devices:
                toggle.configure(text='ON' if variable.get() else 'OFF')
                combo.current(next((i for i, d in enumerate(devices) if d.identifier == preferred), 0))
            else:
                variable.set(False)
                toggle.configure(text='N/A')
                combo.set('Unavailable')
        notice = inventory.notice
        if not inventory.loopbacks:
            notice = notice or 'System audio unavailable · No loopback source detected. Screen + mic works.'
        else:
            notice = 'Detected inputs are checked when recording starts. System audio depends on device routing.'
        self.audio_notice.configure(text=notice)
        self.refresh_button.configure(state='normal')
        self.record_button.configure(state='normal' if backend else 'disabled')
        self.quick_edit_button.configure(state='normal' if backend else 'disabled')
        if error:
            self.show_error(error)
        else:
            self.status.configure(text='● READY', fg=t.GREEN)
            self.message.configure(text='Ready when you are.', fg=t.MUTED)

    def selected_audio(self):
        names = []
        for enabled, combo, devices in ((self.mic_on.get(), self.mic_combo, self.inventory.microphones),
                                        (self.system_on.get(), self.system_combo, self.inventory.loopbacks)):
            if enabled and devices:
                index = combo.current()
                if index < 0:
                    raise ValueError('Select an audio device.')
                names.append(devices[index].identifier)
        return tuple(names)

    def persist(self):
        self.prefs.fps, self.prefs.quality = self.fps.get(), self.quality.get()
        self.prefs.microphone, self.prefs.system_audio = self.mic_on.get(), self.system_on.get()
        self.prefs.hotkey = self.hotkey_on.get()
        self.prefs.watermark = self.watermark_on.get()
        self.prefs.watermark_position = self.watermark_position.get()
        for attr, combo, devices in (('mic_device', self.mic_combo, self.inventory.microphones),
                                     ('system_device', self.system_combo, self.inventory.loopbacks)):
            if devices and combo.current() >= 0:
                setattr(self.prefs, attr, devices[combo.current()].identifier)
        try:
            settings.save(self.prefs)
        except OSError as exc:
            self.message.configure(text=f'Could not save preferences: {exc}', fg=t.RED)

    def toggle(self):
        if self.closing or not self.recorder or self.detecting:
            return
        if self.recorder.busy:
            self.recorder.stop()
            return
        try:
            hwnd = None
            if self.mode.get() == 'window':
                index = self.window_combo.current()
                if index < 0 or index >= len(self.windows):
                    raise ValueError('Select an available window first.')
                hwnd = self.windows[index].hwnd
                validate_window(hwnd)
            watermark = self.watermark_on.get()
            if watermark and not self.watermark_asset.is_file():
                raise RuntimeError('Pulse watermark asset is missing. Reinstall or rebuild Pulse Capture.')
            options = CaptureOptions(
                mode=self.mode.get(), fps=self.fps.get(), quality=self.quality.get(),
                region=self.region, hwnd=hwnd, audio=self.selected_audio(),
                watermark=watermark, watermark_position=self.watermark_position.get(),
                watermark_path=str(self.watermark_asset) if watermark else '')
            options.validate()
            self.persist()
            self.timer.configure(text='00:00:00')
            self.recorder.start(options, self.prefs.output)
            self.lock_controls(True)
        except Exception as exc:
            self.show_error(str(exc))

    def lock_controls(self, locked):
        self.quick_edit_button.configure(state='normal' if self.backend and not locked else 'disabled')
        self.capture_segments.enable(not locked)
        self.fps_segments.enable(not locked)
        self.quality_combo.configure(state='disabled' if locked else 'readonly')
        self.window_combo.configure(state='disabled' if locked else 'readonly')
        self.target_button.configure(state='disabled' if locked else 'normal')
        self.refresh_button.configure(state='disabled' if locked else 'normal')
        self.watermark_toggle.configure(state='disabled' if locked else 'normal')
        self.watermark_combo.configure(
            state='readonly' if self.watermark_on.get() and not locked else 'disabled')
        for combo, toggle, devices in ((self.mic_combo, self.mic_toggle, self.inventory.microphones),
                                       (self.system_combo, self.system_toggle, self.inventory.loopbacks)):
            combo.configure(state='readonly' if devices and not locked else 'disabled')
            toggle.configure(state='normal' if devices and not locked else 'disabled')

    def event(self, event):
        state = event.state
        self.status.configure(text='● ' + state.value.upper(), fg=t.RED if state in (
            State.RECORDING, State.ERROR) else t.GREEN if state == State.SAVED else t.CYAN)
        self.lock_controls(state in (State.STARTING, State.RECORDING, State.STOPPING))
        if state in (State.STARTING, State.RECORDING):
            self.record_button.configure(text='■   STOP RECORDING', bg=t.RED, fg=t.TEXT, state='normal')
            self.message.configure(text='Opening capture devices…' if state == State.STARTING else
                                   'Recording now. Keep the capture target visible.', fg=t.MUTED)
        elif state == State.STOPPING:
            self.record_button.configure(text='FINALIZING RECORDING…', state='disabled')
            self.message.configure(text='Finishing the MP4 and checking the saved video…', fg=t.MUTED)
        else:
            self.record_button.configure(text='●   START RECORDING', bg=t.CYAN, fg=t.BG, state='normal')
            if state == State.SAVED:
                self.last_file = event.path
                self.quick_edit_button.configure(state='normal')
                self.after_idle(lambda: self.canvas.yview_moveto(1) if not self._destroyed else None)
                self.message.configure(text=f'SAVED ✓  {event.path.name}', fg=t.GREEN)
            elif state == State.ERROR:
                suffix = f'\nPartial file: {event.path}' if event.path else ''
                self.show_error(event.message + suffix)
        if self.closing and not self.recorder.busy:
            if state == State.ERROR:
                self.closing = False
                messagebox.showerror('Recording could not be finalized', event.message, parent=self)
            else:
                self.destroy()

    def show_error(self, text):
        self.status.configure(text='● ATTENTION', fg=t.RED)
        self.message.configure(text=text, fg=t.RED)

    def poll(self):
        self._poll_id = None
        try:
            while True:
                self.apply_devices(*self.discoveries.get_nowait())
        except Empty:
            pass
        if self.recorder:
            try:
                while True:
                    self.event(self.recorder.events.get_nowait())
                    if self._destroyed:
                        return
            except Empty:
                pass
            if self.recorder.state == State.RECORDING and self.recorder.started_at:
                elapsed = int(time.monotonic() - self.recorder.started_at)
                h, rem = divmod(elapsed, 3600)
                m, s = divmod(rem, 60)
                self.timer.configure(text=f'{h:02d}:{m:02d}:{s:02d}')
        if self.hotkey.poll():
            self.toggle()
        self._poll_id = self.after(100, self.poll)

    def set_hotkey(self):
        try:
            self.hotkey.enable() if self.hotkey_on.get() else self.hotkey.close()
        except RuntimeError as exc:
            self.hotkey_on.set(False)
            self.show_error(str(exc))
        self.persist()

    def open_quick_edit(self):
        if not self.backend or (self.recorder and self.recorder.busy):
            return
        path = choose_quick_edit_path(self, self.last_file, self.prefs.output)
        if path is None:
            return
        self.last_file = path
        for editor in self.editors:
            if editor.path == path and not editor.closed:
                editor.deiconify()
                editor.lift()
                return
        from editor.editor_window import EditorWindow
        editor = EditorWindow(self, path, self.backend, self.editors.discard)
        self.editors.add(editor)

    def open_folder(self):
        try:
            folder = self.last_file.parent if self.last_file else self.prefs.output
            folder.mkdir(parents=True, exist_ok=True)
            os.startfile(str(folder))
        except OSError as exc:
            self.show_error(f'Could not open the recording folder: {exc}')

    def close(self):
        self.persist()
        self.hotkey.close()
        if self.recorder and self.recorder.busy:
            self.closing = True
            self.recorder.stop()
        else:
            self.destroy()

    def destroy(self):
        if not self._destroyed:
            for editor in list(self.editors):
                editor.close()
            if self.editors:
                self.after(100, self.destroy)
                return
            if self._poll_id:
                self.after_cancel(self._poll_id)
            self._destroyed = True
            self.hotkey.close()
            super().destroy()
