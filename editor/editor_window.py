"""Quick Edit shell; focused panels and services own editing behavior."""
import os
from dataclasses import replace
from pathlib import Path
from queue import Queue, Empty
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk
from ui import theme as t
from .cuts import CutPlan
from .crop_motion import CropMotion
from .cut_tools import CutTools
from .export_job import ExportJob
from .media import probe_media
from .models import TrimRange, format_time, parse_time
from .preview import Preview
from .playback_preview import PlaybackPreview
from .audio_preview import AudioPlayback
from .timeline import Timeline
from .edit_history import EditHistory, EditSnapshot
from .timeline_edits import blocks as timeline_blocks, duration as timeline_duration, change_timing, remove_blocks
from .reaction_preview import ReactionPreview
from .overlay_tools import OverlayTools
from .music_tools import MusicTools
from .polish_tools import PolishTools
from .transforms import EditOptions, Branding, FORMATS, CORNERS, SIZES, SHORTS_FORMAT, FULL_FRAME_FORMAT


class EditorWindow(tk.Toplevel):
    def __init__(self, parent, path, backend, on_close=None, auto_candidate=None, pulse_candidate=None):
        super().__init__(parent)
        self.title('PULSE // CAPTURE — QUICK EDIT')
        self.configure(bg=t.BG)
        self.geometry(f'1180x{min(900, self.winfo_screenheight()-80)}')
        self.minsize(840, 650)
        self.path, self.backend, self.on_close = Path(path), backend, on_close
        self.media = self.trim = self.preview = self.audio_player = None
        self.playback = None
        self.cuts = CutPlan()
        self.auto_candidate = auto_candidate
        self.pulse_candidate = pulse_candidate
        self.auto_dialog = None
        self.auto_children = set()
        self.media_dialog = None
        self.commentary_studio = None
        self._commentary_synced = None
        self.exporter = ExportJob(backend, verify_short=auto_candidate is not None)
        self.metadata = Queue()
        self.closed = self.closing = self.playing = False
        self.position, self.token = 0.0, 0
        self.play_anchor = 0.0
        self.play_anchor_elapsed = 0.0
        self._waiting_for_play_frame = False
        self.last_export = None
        self.output_folder = self.path.parent
        self._seek_id = self._poll_id = self._play_id = None
        self._photo = None
        self.controls = []
        self.edits = EditOptions()
        self.timeline_history = None
        self._timing_drag_key = None
        self.tool = tk.StringVar(value='TRIM')
        self.format_choice = tk.StringVar(value='Original')
        self.comedy_on = tk.BooleanVar(value=False)
        self.brand_on = tk.BooleanVar(value=False)
        self.brand_corner = tk.StringVar(value='Bottom right')
        self.brand_size = tk.StringVar(value='Small')
        self.panels = {}
        self.brand_segments = []
        self.crop_key_buttons = []
        self.audio_on = tk.BooleanVar(value=True)
        self.preview_quality = tk.StringVar(value='480p')
        self.start_text, self.end_text = tk.StringVar(value='0:00.000'), tk.StringVar(value='0:00.000')
        self._build()
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.bind('<Control-z>',self.undo_timeline)
        self.bind('<Control-y>',self.redo_timeline)
        self._poll_id = self.after(60, self.poll)
        def load():
            try:
                self.metadata.put((probe_media(backend.ffprobe, self.path), None))
            except Exception as exc:
                self.metadata.put((None, str(exc)))
        threading.Thread(target=load, daemon=True).start()

    def _build(self):
        # Workspace-first shell: compact header, collapsible tools, real video space.
        tk.Frame(self, height=2, bg=t.CYAN).pack(fill='x')
        header = tk.Frame(self, bg=t.BG)
        header.pack(fill='x', padx=18, pady=(8, 2))
        t.label(header, 'PULSE', 19, bold=True).pack(side='left')
        t.label(header, ' // CAPTURE', 13, t.CYAN).pack(side='left')
        self.workspace_menu = tk.Menubutton(
            header, text='WORKSPACES  ▾', bg=t.CONTROL, fg=t.TEXT,
            activebackground=t.LINE, activeforeground=t.TEXT,
            relief='flat', borderwidth=0, padx=12, pady=7,
            font=(t.FONT, -10, 'bold'), cursor='hand2')
        self.workspace_actions = tk.Menu(
            self.workspace_menu, tearoff=0, bg=t.PANEL, fg=t.TEXT,
            activebackground=t.CYAN, activeforeground=t.BG)
        for caption, action in (
            ('Quick Edit', None),
            ('Auto Edit', self.open_auto_edit),
            ('AI Voiceover', self.open_voiceover_studio),
            ('Roast Studio', self.open_roast_studio)):
            self.workspace_actions.add_command(
                label=caption, command=action,
                state='disabled' if action is None else 'normal')
        if self.pulse_candidate:
            self.workspace_actions.add_separator()
            self.workspace_actions.add_command(label='Edit Pulse Plan',
                                               command=self.open_pulse_plan)
        self.workspace_menu.configure(menu=self.workspace_actions)
        self.workspace_menu.pack(side='right')
        self.controls.append(self.workspace_menu)
        self.source_label = t.label(
            self, self.path.name, 9, t.MUTED, anchor='w')
        self.source_label.pack(fill='x', padx=18, pady=(0, 2))

        # The save controls no longer take an entire oversized bottom section.
        bottom = tk.Frame(self, bg=t.BG)
        self.footer = bottom
        bottom.pack(side='bottom', fill='x', padx=18, pady=(2, 7))
        footer = tk.Frame(bottom, bg=t.BG)
        footer.pack(fill='x')
        messages = tk.Frame(footer, bg=t.BG)
        messages.pack(side='left', fill='x', expand=True)
        self.note = t.label(
            messages, 'Opening your video…', 9, t.MUTED, anchor='w',
            justify='left', wraplength=480)
        self.note.pack(fill='x')
        self.destination = t.label(
            messages, 'Export creates a new copy · original is untouched',
            8, t.MUTED, anchor='w')
        self.destination.pack(fill='x')
        actions = tk.Frame(footer, bg=t.BG)
        actions.pack(side='right', padx=(10, 0))
        self.export_button = t.button(
            actions, 'EXPORT  ↗', self.export, accent=True,
            font=(t.FONT, -12, 'bold'))
        self.export_button.configure(padx=18, pady=9, state='disabled')
        self.export_button.pack(side='right')
        self.cancel_button = t.button(actions, 'CANCEL', self.cancel_export)
        self.open_button = t.button(actions, 'OPEN FOLDER', self.open_folder)
        self.open_button.configure(padx=8, pady=8, font=(t.FONT, -9))
        self.open_button.pack(side='right', padx=(7, 0))
        self.change_folder_button = t.button(
            actions, 'SAVE TO…', self.change_folder)
        self.change_folder_button.configure(
            padx=8, pady=8, font=(t.FONT, -9))
        self.change_folder_button.pack(side='right', padx=(0, 5))
        self.controls.append(self.change_folder_button)
        ttk.Style(self).configure(
            'Pulse.Horizontal.TProgressbar', background=t.CYAN,
            troughcolor=t.CONTROL, bordercolor=t.CONTROL,
            lightcolor=t.CYAN, darkcolor=t.CYAN, thickness=4)
        self.progress = ttk.Progressbar(
            bottom, mode='determinate', maximum=1,
            style='Pulse.Horizontal.TProgressbar')
        self.progress.pack(fill='x', pady=(4, 0))

        workspace = tk.Frame(self, bg=t.BG)
        workspace.pack(fill='both', expand=True, padx=16, pady=(5, 4))

        # Tools move down a narrow vertical rail; clicking one opens its
        # dedicated inspector. No panel takes preview height by default.
        rail = tk.Frame(workspace, bg=t.PANEL, width=116)
        rail.pack(side='left', fill='y', padx=(0, 10))
        rail.pack_propagate(False)
        t.label(rail, 'TOOLS', 10, t.CYAN, True).pack(anchor='w', padx=10, pady=(7, 4))
        self.add_menu = tk.Menubutton(
            rail, text='+  ADD  ▾', bg=t.CYAN, fg=t.BG,
            activebackground=t.LINE, activeforeground=t.TEXT,
            relief='flat', borderwidth=0, padx=7, pady=8,
            font=(t.FONT, -10, 'bold'), cursor='hand2')
        add_actions = tk.Menu(
            self.add_menu, tearoff=0, bg=t.PANEL, fg=t.TEXT,
            activebackground=t.CYAN, activeforeground=t.BG)
        add_actions.add_command(label='Photo / Video', command=self.open_imported_media)
        add_actions.add_command(label='Emoji', command=lambda: self.open_reactions('emoji'))
        add_actions.add_command(label='GIF / Reaction', command=lambda: self.open_reactions('gif'))
        add_actions.add_command(label='Sound Effect', command=lambda: self.open_reactions('sfx'))
        add_actions.add_command(label='🎙 Record Commentary', command=self.open_commentary_studio)
        add_actions.add_command(label='Effects', command=lambda: self.open_reactions('effects'))
        self.add_menu.configure(menu=add_actions, state='disabled')
        self.add_menu.pack(fill='x', padx=8, pady=(0, 5))
        self.controls.append(self.add_menu)
        self.tool_buttons = {}
        self.tool_titles = {
            'TRIM': 'Trim', 'CUT': 'Cut', 'FORMAT': 'Canvas',
            'CROP': 'Crop', 'BRAND': 'Watermark', 'TEXT': 'Text',
            'PRIVACY': 'Privacy', 'MOTION': 'Motion',
            'MUSIC': 'Music', 'FINISH': 'Export'}
        for name, caption in self.tool_titles.items():
            button = t.button(
                rail, caption, lambda tool=name: self.toggle_tool(tool))
            button.configure(
                padx=5, pady=2, font=(t.FONT, -10, 'bold'),
                state='disabled')
            button.pack(fill='x', padx=8, pady=1)
            self.tool_buttons[name] = button
            self.controls.append(button)

        self.work_panes = tk.PanedWindow(
            workspace, orient='horizontal', bg=t.BG, sashwidth=9,
            sashrelief='flat', showhandle=True, handlesize=13,
            relief='flat', bd=0)
        self.work_panes.pack(side='left', fill='both', expand=True)
        self.work_panes.bind('<ButtonRelease-1>', self._remember_inspector_width)

        # Existing tool panels use the same models/handlers but now dock to
        # the right of the preview, not beneath it.
        self.inspector = tk.Frame(
            self.work_panes, bg=t.PANEL, width=440,
            highlightbackground=t.LINE, highlightthickness=1)
        self.inspector.pack_propagate(False)
        self.inspector_width = 440
        self.inspector_visible = False
        inspector_head = tk.Frame(self.inspector, bg=t.PANEL)
        inspector_head.pack(fill='x', padx=10, pady=(6, 0))
        self.inspector_title = t.label(
            inspector_head, 'TRIM', 10, t.CYAN, True)
        self.inspector_title.pack(side='left')
        self.inspector_close = t.button(
            inspector_head, '✕  CLOSE TOOLS', self.hide_inspector)
        self.inspector_close.configure(
            font=(t.FONT, -9, 'bold'), padx=9, pady=3)
        self.inspector_close.pack(side='right')
        # Embed the existing wide/long legacy tool controls in an inspector
        # viewport. This prevents their natural requested size from squeezing
        # the video; both scroll axes remain available when a tool is wider.
        tool_area = tk.Frame(self.inspector, bg=t.PANEL)
        tool_area.pack(fill='both', expand=True, padx=(7, 3), pady=(4, 6))
        self.tool_scroll_x = ttk.Scrollbar(
            tool_area, orient='horizontal', command=self.tool_canvas_xview)
        self.tool_scroll_x.pack(side='bottom', fill='x')
        content = tk.Frame(tool_area, bg=t.PANEL)
        content.pack(fill='both', expand=True)
        self.tool_scroll_y = ttk.Scrollbar(
            content, orient='vertical')
        self.tool_scroll_y.pack(side='right', fill='y')
        self.tool_canvas = tk.Canvas(
            content, bg=t.PANEL, bd=0, highlightthickness=0,
            xscrollcommand=self.tool_scroll_x.set,
            yscrollcommand=self.tool_scroll_y.set)
        self.tool_canvas.pack(side='left', fill='both', expand=True)
        self.tool_scroll_y.configure(command=self.tool_canvas.yview)
        self.panel_area = tk.Frame(self.tool_canvas, bg=t.PANEL)
        self.tool_canvas_item = self.tool_canvas.create_window(
            0, 0, window=self.panel_area, anchor='nw')
        self.tool_canvas.bind('<Configure>', self._inspector_canvas_resized)
        self.panel_area.bind('<Configure>', self._inspector_content_resized)
        self.tool_canvas.bind('<MouseWheel>', self._inspector_wheel)
        panel_area = self.panel_area
        for name in ('TRIM', 'CUT', 'FORMAT', 'CROP', 'BRAND', 'TEXT', 'PRIVACY', 'MOTION', 'MUSIC', 'FINISH'):
            self.panels[name] = tk.Frame(panel_area, bg=t.PANEL)
        row = self.panels['TRIM']
        row.pack(fill='both', expand=True, padx=12, pady=10)
        row.columnconfigure(0, weight=1)
        for column, (title, variable, bound) in enumerate(
                (('Start', self.start_text, 'start'), ('End', self.end_text, 'end'))):
            group = tk.Frame(row, bg=t.PANEL)
            group.grid(row=column, column=0, sticky='ew', pady=(0, 9))
            t.label(group, title, 10, bold=True).pack(anchor='w')
            inner = tk.Frame(group, bg=t.PANEL)
            inner.pack(fill='x', pady=(5, 0))
            entry = tk.Entry(inner, textvariable=variable, bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN,
                             relief='flat', width=13, font=(t.MONO, -17), disabledbackground=t.CONTROL)
            entry.pack(side='left', ipady=7)
            entry.bind('<Return>', lambda _: self.commit_entries())
            entry.bind('<FocusOut>', lambda _: self.commit_entries())
            button = t.button(inner, 'USE PLAYHEAD', lambda b=bound: self.use_playhead(b))
            button.configure(font=(t.FONT, -10, 'bold'), padx=8)
            button.pack(side='left', padx=(8, 0))
            self.controls.extend((entry, button))
        self.reset_button = t.button(row, 'RESET', self.reset_trim)
        self.reset_button.grid(row=2, column=0, sticky='w')
        self.controls.append(self.reset_button)
        self.selection_label = t.label(row, 'Drag the cyan handles or enter Start and End.', 9, t.MUTED)
        self.selection_label.grid(row=3, column=0, sticky='w', pady=(8, 0))
        self.build_tools()
        self.cut_tools = CutTools(self)
        self.overlay_tools = OverlayTools(self)
        self.music_tools = MusicTools(self)
        self.polish_tools = PolishTools(self)
        for widget in self.controls:
            widget.configure(state='disabled')

        preview_area = tk.Frame(self.work_panes, bg=t.BG)
        self.work_panes.add(preview_area, minsize=300, stretch='always')
        self.preview_split = tk.PanedWindow(
            preview_area, orient='vertical', bg=t.BG,
            sashwidth=8, sashrelief='flat',
            relief='flat', bd=0, showhandle=True,
            handlesize=12, handlepad=8)
        self.preview_split.pack(fill='both', expand=True)
        self.video = ReactionPreview(
            self.preview_split, self.crop_changed,
            self.overlay_tools.mask_changed,
            self.polish_tools.focus_changed,
            window=self, bg='#060a10',
            highlightbackground=t.LINE, highlightthickness=1,
            height=350)
        self.preview_split.add(self.video, minsize=160, stretch='always')
        self.video.bind('<Configure>', self.resize_preview)
        self.video.create_text(
            350, 120, text='Opening your video…',
            fill=t.MUTED, tags='placeholder')
        timeline_space = tk.Frame(self.preview_split, bg=t.BG)
        self.preview_split.add(
            timeline_space, minsize=115, stretch='never')
        transport = tk.Frame(timeline_space, bg=t.BG)
        transport.pack(fill='x', pady=(2, 2))
        self.play_button = t.button(transport, '▶  PLAY', self.play_preview)
        self.pause_button = t.button(transport, '⏸  PAUSE', self.pause_preview)
        self.stop_button = t.button(transport, '■  STOP', self.stop_preview)
        for button in (self.play_button, self.pause_button, self.stop_button):
            button.configure(state='disabled', padx=10, pady=6)
        self.play_button.pack(side='left')
        self.pause_button.pack(side='left', padx=(5, 0))
        self.stop_button.pack(side='left', padx=(5, 0))
        self.clock = t.label(
            transport, '0:00.000 / 0:00.000', 10, t.TEXT)
        self.clock.pack(side='left', padx=12)
        # Audio status remains available to diagnostics, but the transport bar
        # shows only playback controls; the old explanatory note crowded small PCs.
        self.preview_note = t.label(
            transport, 'Preparing audio preview…', 9, t.MUTED)
        self.quality_picker = ttk.Combobox(
            transport, textvariable=self.preview_quality,
            values=('360p', '480p', '720p'),
            state='readonly', width=5)
        self.quality_picker.pack(side='right', padx=5)
        self.quality_picker.bind(
            '<<ComboboxSelected>>', self.quality_changed)
        self.audio_toggle = tk.Checkbutton(
            transport, text='SOUND ON', variable=self.audio_on,
            command=self.toggle_audio, bg=t.BG, fg=t.CYAN,
            selectcolor=t.CONTROL, activebackground=t.BG,
            activeforeground=t.TEXT, disabledforeground=t.MUTED,
            bd=0)
        self.audio_toggle.pack(side='right', padx=(0, 7))
        self.timeline = Timeline(
            timeline_space, self.seek, self.drag_trim,
            self.begin_clip_drag, self.change_clip_drag,
            self.end_clip_drag, self.delete_timeline_item)
        self.timeline.on_output_seek = self.seek_output_time
        self.timeline.pack(fill='x')
        self.paint_tool_buttons()

    def add_segments(self, parent, variable, choices, command):
        segments = t.Segments(parent, variable, choices, command)
        segments.pack(fill='x', pady=(0, 6))
        if len(choices) >= 4:
            # Five landscape format choices become a tidy two-column list
            # when presented in the compact right-side inspector.
            for index, (_, button) in enumerate(segments.buttons):
                button.grid_configure(
                    row=index // 2, column=index % 2,
                    padx=(0 if index % 2 == 0 else 5, 0),
                    pady=(0, 4))
            for col in range(len(choices)):
                segments.columnconfigure(col, weight=1 if col < 2 else 0)
        self.controls.extend(b for _, b in segments.buttons)
        return segments

    def open_imported_media(self):
        if not self.media or self.exporter.busy or self.closing:
            return
        if self.media_dialog and not self.media_dialog.closed:
            self.media_dialog.deiconify()
            self.media_dialog.lift()
            return
        from .imported_media_ui import ImportedMediaDialog
        self.media_dialog = ImportedMediaDialog(self)

    def open_commentary_studio(self):
        """Record, edit and convert commentary without leaving Quick Edit."""
        if not self.media or not self.trim or self.exporter.busy or self.closing:
            return
        if self.commentary_studio is not None and self.commentary_studio.winfo_exists():
            self.commentary_studio.deiconify()
            self.commentary_studio.lift()
            return
        from .commentary_ui import CommentaryStudio
        self.commentary_studio = CommentaryStudio(self)

    def open_voiceover_studio(self):
        """Open the standalone narration generator without changing video edit state."""
        from .ai_voiceover_ui import VoiceoverStudio
        VoiceoverStudio(self)

    def open_reactions(self, kind):
        if not self.media or self.exporter.busy or self.closing:
            return
        self.stop_play()
        if kind == 'effects':
            from .pulse_tools import open_plan_dialog
            if self.pulse_candidate:
                plan, source = self.pulse_candidate
                dialog = open_plan_dialog(self, plan=plan, media=source)
            else:
                dialog = open_plan_dialog(self, template=True)
            dialog.notebook.select(dialog.effects_panel)
        else:
            from .reaction_tools import ReactionDialog
            existing = next((child for child in self.auto_children if isinstance(child, ReactionDialog)
                             and child.kind == kind and not child.closed), None)
            if existing:
                existing.deiconify()
                existing.lift()
                return
            ReactionDialog(self, kind)

    def open_roast_studio(self):
        if not self.media or self.exporter.busy or self.closing:
            return
        from .roast_studio import RoastStudioDialog
        existing = next((child for child in self.auto_children
                         if isinstance(child, RoastStudioDialog) and not child.closed), None)
        if existing:
            existing.lift()
            return
        self.stop_play()
        studio = RoastStudioDialog(self)
        self.auto_children.add(studio)

    def open_auto_edit(self):
        if not self.media or self.exporter.busy or self.closing:
            return
        self.stop_play()
        if self.auto_dialog and not self.auto_dialog.closed:
            self.auto_dialog.lift()
            return
        from .auto_tools import AutoEditDialog
        self.auto_dialog = AutoEditDialog(self)

    def load_auto_candidate(self):
        from .auto_plan import editor_state
        short, transcript, mode = self.auto_candidate[:3]
        style = self.auto_candidate[3] if len(self.auto_candidate) > 3 else None
        trim, cuts, edits = editor_state(short, self.media, transcript, style=style)
        self.cuts, self.edits = cuts, edits
        self.format_choice.set(edits.preset)
        self.position = trim.start
        self.update_trim(trim)
        self.select_tool('FORMAT')
        self.title(f'PULSE · {mode} · {short["title"]}')
        self.source_label.configure(text=f'{mode} · {short["title"]} · Review before publishing')
        self.note.configure(text='Review the whole Short; adjust Crop, Cut or Text before exporting.',
                            fg=t.CYAN)

    def open_pulse_plan(self):
        from .pulse_tools import open_plan_dialog
        plan, source = self.pulse_candidate
        open_plan_dialog(self, plan=plan, media=source)

    def load_pulse_candidate(self):
        from .auto_plan import editor_state
        plan, source = self.pulse_candidate
        trim, self.cuts, self.edits = editor_state(plan, source, assembled_media=self.media)
        self.format_choice.set(self.edits.preset)
        self.comedy_on.set(self.edits.comedy_bands is not None)
        self.update_trim(trim)
        self.select_tool('TEXT')
        self.title(f'PULSE · Pulse Plan · {plan["title"]}')
        self.source_label.configure(text=f'{plan["title"]} · Assembled review · Original: {source.path.name}')
        self.note.configure(text='Review the whole Short. Edit captions in Text; use EDIT PULSE PLAN to revise shots and title cards.', fg=t.CYAN)

    def build_tools(self):
        # Keep the legacy internal format names for older edits/tests, but show
        # a clear horizontal + Shorts choice instead of two identical 9:16 tabs.
        format_choices = [('Original', 'Original'),
                          (FULL_FRAME_FORMAT, 'Shorts\nFull Frame'),
                          ('16:9 Landscape', '16:9\nHorizontal'),
                          (SHORTS_FORMAT, 'Shorts\nCrop to Fill'),
                          ('1:1 Square', '1:1\nSquare')]
        panel = self.panels['FORMAT']
        self.add_segments(panel, self.format_choice, format_choices, self.format_changed)
        t.label(panel, 'Full Frame keeps the whole picture on a dark 1080 × 1920 canvas.', 9, t.MUTED).pack(anchor='w')
        row=tk.Frame(panel,bg=t.PANEL);row.pack(fill='x',pady=(4,0))
        toggle=tk.Checkbutton(row,text='COMEDY LAYOUT — safe caption bands',variable=self.comedy_on,
                              command=self.comedy_changed,bg=t.PANEL,fg=t.CYAN,selectcolor=t.CONTROL)
        toggle.pack(side='left');self.controls.append(toggle)
        button=t.button(row,'BAND CAPTIONS',lambda:self.overlay_tools.edit_captions())
        button.configure(pady=3,font=(t.FONT,-10,'bold'));button.pack(side='right');self.controls.append(button)
        panel = self.panels['CROP']
        self.add_segments(panel, self.format_choice, format_choices, self.format_changed)
        self.crop_hint = t.label(panel, 'Choose a shape, then drag the cyan frame to keep what matters.', 9, t.MUTED)
        self.crop_hint.pack(anchor='w', pady=(0, 6))
        actions = tk.Frame(panel, bg=t.PANEL)
        actions.pack(fill='x')
        # Reuse the current crop tool rather than adding another editor tab.
        for label, command, keyed in (
                ('CENTRE', self.center_crop, False),
                ('ADD KEY', self.add_crop_keyframe, True),
                ('◀ KEY', lambda: self.jump_crop_keyframe(-1), True),
                ('KEY ▶', lambda: self.jump_crop_keyframe(1), True),
                ('DELETE KEY', self.delete_crop_keyframe, True),
                ('CLEAR KEYS', self.clear_crop_keyframes, True),
                ('VIEW RESULT', lambda: self.select_tool('FORMAT'), False)):
            button = t.button(actions, label, command)
            button.configure(font=(t.FONT, -9, 'bold'), padx=6, pady=4)
            button.pack(side='left', padx=(0, 6))
            self.controls.append(button)
            if keyed:
                self.crop_key_buttons.append(button)
        panel = self.panels['BRAND']
        row = tk.Frame(panel, bg=t.PANEL)
        row.pack(fill='x')
        toggle = tk.Frame(row, bg=t.PANEL)
        toggle.pack(side='left', padx=(0, 14))
        self.add_segments(toggle, self.brand_on, [(False, 'OFF'), (True, 'ON')], self.brand_changed)
        sizes = tk.Frame(row, bg=t.PANEL)
        sizes.pack(side='left', fill='x', expand=True)
        self.brand_segments.append(self.add_segments(sizes, self.brand_size,
                                  [(v, v) for v in SIZES], self.brand_changed))
        self.brand_segments.append(self.add_segments(panel, self.brand_corner,
                                  [(v, v) for v in CORNERS], self.brand_changed))
        t.label(panel, 'Adds a new logo. A logo already in the recording cannot be removed.',
                9, t.MUTED).pack(anchor='w')

    def tool_canvas_xview(self, *args):
        self.tool_canvas.xview(*args)

    def _inspector_canvas_resized(self, event=None):
        """Let narrow panels fill the right dock while wider tools can scroll."""
        if not hasattr(self, 'tool_canvas_item'):
            return
        viewport = event.width if event is not None else self.tool_canvas.winfo_width()
        requested = self.panel_area.winfo_reqwidth()
        self.tool_canvas.itemconfigure(
            self.tool_canvas_item, width=max(1, viewport, requested))
        self._inspector_content_resized()

    def _inspector_content_resized(self, _event=None):
        self.tool_canvas.configure(scrollregion=self.tool_canvas.bbox('all'))

    def _inspector_wheel(self, event):
        if not self.inspector_visible:
            return
        if event.state & 0x1:
            self.tool_canvas.xview_scroll(-1 if event.delta > 0 else 1, 'units')
        else:
            self.tool_canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
        return 'break'

    def _remember_inspector_width(self, _event=None):
        if self.inspector_visible:
            width = self.inspector.winfo_width()
            if width > 250:
                self.inspector_width = width

    def _refresh_inspector_view(self):
        """Recompute scroll bounds for every newly selected tool."""
        if not self.inspector_visible or self.closed or self.closing:
            return
        self._inspector_canvas_resized()
        self.tool_canvas.configure(scrollregion=self.tool_canvas.bbox('all'))

    def paint_tool_buttons(self):
        """Keep the current tool discoverable without filling the header."""
        for name, button in self.tool_buttons.items():
            active = self.inspector_visible and self.tool.get() == name
            button.configure(
                bg=t.CYAN if active else t.CONTROL,
                fg=t.BG if active else t.TEXT)

    def toggle_tool(self, name):
        if self.inspector_visible and self.tool.get() == name:
            self.hide_inspector()
        else:
            self.select_tool(name)

    def select_tool(self, name):
        if name not in self.panels:
            raise ValueError('Unknown editor tool.')
        self.tool.set(name)
        self.show_tool()

    def hide_inspector(self):
        if not self.inspector_visible:
            return
        self.stop_play()
        self._remember_inspector_width()
        self.work_panes.forget(self.inspector)
        self.inspector_visible = False
        # When no tool is open, show the actual edited picture rather than
        # lingering source crop/privacy guides from the previous panel.
        self.tool.set('TRIM')
        self.video.active = False
        self.video.drag = None
        self.video.media_drag = None
        self.video.zoom_drag = False
        self.cut_tools.refresh()
        self.overlay_tools.refresh()
        self.music_tools.refresh()
        self.polish_tools.refresh()
        self.paint_tool_buttons()
        if self.media and self.trim:
            self.update_timeline()
        self.request_frame()

    def show_tool(self):
        self.stop_play()
        for panel in self.panels.values():
            panel.pack_forget()
        self.panels[self.tool.get()].pack(
            fill='both', expand=True, padx=12, pady=8)
        self.inspector_title.configure(
            text=self.tool_titles[self.tool.get()].upper() + '  //  SETTINGS')
        if not self.inspector_visible:
            self.work_panes.add(
                self.inspector, minsize=280, width=self.inspector_width,
                stretch='never')
            self.inspector_visible = True
        # Existing inspector entries may be much wider than the dock; their
        # scrollbars make them usable without forcing video out of sight.
        self.tool_canvas.xview_moveto(0)
        self.tool_canvas.yview_moveto(0)
        self.after_idle(self._refresh_inspector_view)
        self.paint_tool_buttons()
        self.video.active = self.tool.get() == 'CROP'
        self.video.drag = None
        self.video.media_drag = None
        self.video.zoom_drag = False
        self.cut_tools.refresh()
        self.overlay_tools.refresh()
        self.music_tools.refresh()
        self.polish_tools.refresh()
        if self.media and self.trim:
            self.update_timeline()
        self.request_frame()

    def format_changed(self):
        if not self.media or self.exporter.busy:
            return
        try:
            if self.format_choice.get() != self.edits.preset:
                self.edits = self.edits.with_format(self.media, self.format_choice.get())
            self.comedy_on.set(self.edits.comedy_bands is not None)
            self.video.crop = self.edits.crop
            self.overlay_tools.refresh()
            self.polish_tools.refresh()
            self.stop_play()
            self.refresh_crop_guide()
            self.update_timeline()
            self.request_frame()
        except ValueError as exc:
            self.format_choice.set(self.edits.preset)
            self.note.configure(text=str(exc), fg=t.RED)

    def comedy_changed(self):
        if not self.media or self.exporter.busy:return
        try:
            if self.comedy_on.get():
                if self.pulse_candidate:
                    plan,source=self.pulse_candidate
                    if plan['output']['framing'] not in ('full_frame','comedy_bands'):
                        raise ValueError('Re-render this plan using full_frame or comedy_bands to preserve the whole picture.')
                    dimensions=(source.width,source.height)
                    proposed=replace(self.edits,comedy_bands=dimensions)
                else:
                    proposed=replace(self.edits.with_format(self.media,FULL_FRAME_FORMAT),
                                     comedy_bands=(self.media.width,self.media.height))
            else:
                if any(c.zone!='canvas' for c in self.edits.overlays):
                    raise ValueError('Set band overlays to Canvas before disabling Comedy Layout.')
                proposed=replace(self.edits,comedy_bands=None)
            proposed.validate(self.media)
            self.stop_play();self.edits=proposed;self.format_choice.set(proposed.preset)
            self.update_timeline();self.request_frame()
            self.note.configure(text='Comedy bands ready. Add Top / Bottom captions and choose a band for emoji or GIF reactions.',fg=t.CYAN)
        except ValueError as exc:
            self.comedy_on.set(self.edits.comedy_bands is not None)
            self.note.configure(text=str(exc),fg=t.RED)

    def refresh_crop_guide(self):
        if not self.media or not hasattr(self, 'video'):
            return
        try:
            self.video.crop = self.edits.crop_at(self.media, self.position)
        except ValueError as exc:
            # An invalid draft is reported during editing; never crash Tk.
            self.video.crop = self.edits.crop
            self.note.configure(text=str(exc), fg=t.RED)
        self.video.draw_overlay()
        count = len(self.edits.crop_motion.keyframes)
        shorts = self.edits.preset == SHORTS_FORMAT
        for button in self.crop_key_buttons:
            button.configure(state='normal' if shorts and not self.exporter.busy and
                             not self.closing else 'disabled')
        if shorts:
            message = (f'{count} crop key(s) · Drag inside to move; drag corners to resize all keys. '
                       'Motion follows the saved positions.'
                       if count else
                       'Shorts: drag inside to move, corners to resize, then ADD KEY to animate.')
        elif self.edits.crop:
            message = 'Drag inside to move. Drag a cyan corner to resize; aspect ratio stays locked.'
        else:
            message = 'Original uses the full frame. Select Horizontal or YouTube Shorts to crop.'
        self.crop_hint.configure(text=message)

    def crop_changed(self, crop):
        if self.exporter.busy or self.closing:
            return
        self.stop_play()
        try:
            if self.edits.crop_motion.keyframes:
                # A resize applies to the whole clip; keyframe centres are
                # retained, then the current playhead receives its resized crop.
                if (crop.width, crop.height) != (self.edits.crop.width, self.edits.crop.height):
                    keys = self.edits.crop_motion.reframed(self.media, self.edits.crop, crop)
                    keys = keys.at(self.media, crop, self.position)
                    proposed = replace(self.edits, crop=crop, crop_motion=keys)
                else:
                    # Dragging at a new playhead position records the movement.
                    keys = self.edits.crop_motion.at(self.media, crop, self.position)
                    proposed = replace(self.edits, crop_motion=keys)
            else:
                proposed = replace(self.edits, crop=crop)
            proposed.validate(self.media)
            self.edits = proposed
            self.refresh_crop_guide()
            self.update_timeline()
            self.overlay_tools.refresh()
            self.polish_tools.refresh()
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def add_crop_keyframe(self):
        if not self.media or self.edits.preset != SHORTS_FORMAT or self.exporter.busy:
            return
        self.stop_play()
        try:
            crop = self.edits.crop_at(self.media, self.position)
            motion = self.edits.crop_motion.at(self.media, crop, self.position)
            proposed = replace(self.edits, crop_motion=motion)
            proposed.validate(self.media)
            self.edits = proposed
            self.refresh_crop_guide()
            self.update_timeline()
            self.note.configure(text=f'Crop keyframe saved at {format_time(self.position)}.', fg=t.CYAN)
            self.request_frame()
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def jump_crop_keyframe(self, direction):
        if not self.media or not self.edits.crop_motion.keyframes or self.exporter.busy:
            return
        margin = .50001 / self.media.fps
        keys = self.edits.crop_motion.keyframes
        key = next((k for k in (keys if direction > 0 else reversed(keys))
                    if (k.time > self.position+margin if direction > 0
                        else k.time < self.position-margin)), None)
        if key:
            self.seek(key.time)

    def delete_crop_keyframe(self):
        if not self.media or self.exporter.busy or self.edits.preset != SHORTS_FORMAT:
            return
        self.stop_play()
        try:
            motion = self.edits.crop_motion.remove_at(self.media, self.edits.crop, self.position)
            self.edits = replace(self.edits, crop_motion=motion)
            self.refresh_crop_guide()
            self.update_timeline()
            self.request_frame()
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def clear_crop_keyframes(self):
        if not self.media or self.exporter.busy or self.edits.preset != SHORTS_FORMAT:
            return
        self.stop_play()
        crop = self.edits.crop_at(self.media, self.position)
        self.edits = replace(self.edits, crop=crop, crop_motion=CropMotion())
        self.refresh_crop_guide()
        self.update_timeline()
        self.request_frame()

    def center_crop(self):
        if not self.media or self.exporter.busy:
            return
        self.stop_play()
        current = self.edits.crop_at(self.media, self.position)
        if current is None:
            return
        centered = current.moved(self.media,
                                (self.media.width-current.width)/2,
                                (self.media.height-current.height)/2)
        if self.edits.crop_motion.keyframes:
            motion = self.edits.crop_motion.at(self.media, centered, self.position)
            self.edits = replace(self.edits, crop_motion=motion)
        else:
            self.edits = replace(self.edits, crop=centered)
        self.refresh_crop_guide()
        self.update_timeline()
        self.overlay_tools.refresh()
        self.polish_tools.refresh()
        self.request_frame()

    def update_brand_controls(self):
        enabled = bool(self.media and not self.exporter.busy and self.brand_on.get())
        for segments in self.brand_segments:
            segments.enable(enabled)

    def brand_changed(self):
        self.edits = replace(self.edits, branding=Branding(self.brand_on.get(),
                             self.brand_corner.get(), self.brand_size.get()))
        self.update_brand_controls()
        self.stop_play()
        self.request_frame()

    def resize_preview(self, _=None):
        self.video.coords('placeholder', self.video.winfo_width()/2, self.video.winfo_height()/2)
        self.video.coords('frame', self.video.winfo_width()/2, self.video.winfo_height()/2)
        self.video.drag = None
        self.video.zoom_drag = False
        self.video.gesture = self.video.candidate = None
        self.video.media_drag = None
        self.video.draw_overlay()
        if self.preview and not self.playing:
            self.request_frame()

    def request_frame(self):
        if not self.preview or self.closed or self.closing:
            return
        if self.playing:self.stop_play()
        self.refresh_crop_guide()
        self.token += 1
        token = self.token
        if self._seek_id:
            self.after_cancel(self._seek_id)
        def send():
            self._seek_id = None
            edits = self.edits
            if self.tool.get() == 'PRIVACY':
                edits = self.overlay_tools.preview_edits(edits)
                # Source-anchored rectangle editing needs unzoomed, visible pixels.
                edits = replace(edits, zoom=replace(edits.zoom, enabled=False),
                                fade=replace(edits.fade, fade_in=False, fade_out=False))
            if (self.tool.get() == 'MOTION' and edits.zoom.enabled
                    and not self.polish_tools.zoom_result):
                # Focus placement must remain visible even at a fade boundary.
                edits = replace(edits, zoom=replace(edits.zoom, enabled=False),
                                fade=replace(edits.fade, fade_in=False, fade_out=False))
            self.preview.request(token, self.position,
                                 self.video.winfo_width()-4, self.video.winfo_height()-4,
                                 edits, self.tool.get() == 'CROP', self.trim, self.cuts)
        self._seek_id = self.after(90 if not self.playing else 1, send)

    def quality_changed(self, _=None):
        resume=self.playing
        self.stop_play()
        if resume:self.play_preview()
        else:self.request_frame()

    def seek(self, position):
        self.stop_play()
        self.position = max(0, min(position, self.media.duration))
        self.update_timeline()
        self.request_frame()

    def update_timeline(self, position_only=False):
        if position_only or (
            self.playing
            and self.timeline.media is self.media
            and self.timeline.trim == self.trim
            and self.timeline.cuts == self.cuts
        ):
            self.timeline.move_playhead(self.position)
            self.clock.configure(text=f'{format_time(self.position)} / {format_time(self.media.duration)}')
            return
        self.timeline.media, self.timeline.trim, self.timeline.position = self.media, self.trim, self.position
        self.timeline.cuts = self.cuts
        self.timeline.crop_keyframes = (self.edits.crop_motion.keyframes
                                        if self.tool.get() == 'CROP' else ())
        self.timeline.cut_draft = (
            self.cut_tools.draft()
            if hasattr(self, 'cut_tools') and self.tool.get() == 'CUT'
            else (None, None)
        )
        self.timeline.reaction_markers = tuple(
            (self.cuts.source_from_elapsed((c.at if hasattr(c, 'at') else c.start)*self.edits.speed, self.trim),
             'SFX' if hasattr(c, 'at') else c.kind.upper())
            for c in (*self.edits.sounds, *self.edits.overlays))
        self.timeline.output_duration = timeline_duration(self) if self.media and self.trim else 0
        self.timeline.clip_blocks = tuple(timeline_blocks(self)) if self.media and self.trim else ()
        if (self.commentary_studio is not None and
                self.commentary_studio.winfo_exists() and
                self._commentary_synced != self.edits.commentary_clips):
            self._commentary_synced = self.edits.commentary_clips
            self.commentary_studio.refresh()
        self.timeline.draw()
        self.clock.configure(text=f'{format_time(self.position)} / {format_time(self.media.duration)}')
        self.refresh_crop_guide()

    def seek_output_time(self, at):
        if not self.media or not self.trim:return
        self.seek(self.cuts.source_from_elapsed(at*self.edits.speed,self.trim))

    def begin_clip_drag(self, key):
        if not self.media or self.exporter.busy or self.closing:return
        self.stop_play()
        state=EditSnapshot(self.trim,self.cuts,self.edits)
        if self.timeline_history is None or self.timeline_history.current!=state:
            # Existing tools may have edited the project since the last drag.
            # Never undo across edits we did not record.
            self.timeline_history=EditHistory(state)
        self.timeline_history.begin()
        self._timing_drag_key=key

    def change_clip_drag(self, key, start, end):
        if self._timing_drag_key!=key or not self.media or self.exporter.busy:return
        try:
            state=EditSnapshot(self.trim,self.cuts,self.edits)
            updated=change_timing(state,key,start,end,self.media)
            if updated==state:return
            self.edits=updated.edits
            self.timeline_history.record(updated)
            self.update_timeline()
            # Preview the altered timing once on release, not a costly FFmpeg
            # seek on every mouse pixel: preserve smooth continuous decoding.
        except (ValueError,IndexError) as exc:
            self.note.configure(text=str(exc),fg=t.RED)

    def end_clip_drag(self):
        if self.timeline_history:self.timeline_history.end()
        if self._timing_drag_key is None:return
        self._timing_drag_key=None
        self.overlay_tools.refresh()
        if self.media_dialog and not self.media_dialog.closed:
            self.media_dialog.refresh()
        self.request_frame()

    def delete_timeline_item(self, key):
        """One undoable operation for right-click and Delete key on a timeline block."""
        if not self.media or self.exporter.busy or self.closing:
            return
        if key not in {block.key for block in self.timeline.clip_blocks
                       if block.kind in self.timeline.DELETABLE}:
            return
        self.stop_play()
        if self._timing_drag_key is not None:
            self.end_clip_drag()
        before = EditSnapshot(self.trim, self.cuts, self.edits)
        try:
            after = remove_blocks(before, (key,), self.media)
        except (ValueError, IndexError) as exc:
            self.note.configure(text=str(exc), fg=t.RED)
            return
        if self.timeline_history is None or self.timeline_history.current != before:
            self.timeline_history = EditHistory(before)
        self.timeline_history.end()
        self.timeline_history.record(after)
        self.edits = after.edits
        self.timeline.selected_key = None
        # Don't retain a selection reference to a removed media/emoji index.
        self.video.select_media(None, notify=False)
        self.video.select_visual(None)
        self.update_timeline()
        self.overlay_tools.refresh()
        self.music_tools.sync()
        self.music_tools.refresh()
        self.polish_tools.sync()
        self.polish_tools.refresh()
        if self.media_dialog and not self.media_dialog.closed:
            self.media_dialog.refresh()
        self.request_frame()
        self.note.configure(text=f'Deleted {key[0].replace("_", " ")} from timeline · Ctrl+Z to undo.',
                            fg=t.CYAN)

    def undo_timeline(self, _event=None):
        if not self.timeline_history or not self.media or self.exporter.busy:return
        state=EditSnapshot(self.trim,self.cuts,self.edits)
        if self.timeline_history.current!=state:return
        if not self.timeline_history.past:return
        self.stop_play()
        restored=self.timeline_history.undo()
        self.edits=restored.edits
        self.timeline.selected_key = None
        self.video.select_media(None, notify=False)
        self.video.select_visual(None)
        self.update_timeline();self.overlay_tools.refresh();self.request_frame()
        self.music_tools.sync();self.music_tools.refresh()
        self.polish_tools.sync();self.polish_tools.refresh()
        if self.media_dialog and not self.media_dialog.closed:self.media_dialog.refresh()
        return 'break'

    def redo_timeline(self, _event=None):
        if not self.timeline_history or not self.media or self.exporter.busy:return
        state=EditSnapshot(self.trim,self.cuts,self.edits)
        if self.timeline_history.current!=state:return
        if not self.timeline_history.future:return
        self.stop_play()
        restored=self.timeline_history.redo()
        self.edits=restored.edits
        self.timeline.selected_key = None
        self.video.select_media(None, notify=False)
        self.video.select_visual(None)
        self.update_timeline();self.overlay_tools.refresh();self.request_frame()
        self.music_tools.sync();self.music_tools.refresh()
        self.polish_tools.sync();self.polish_tools.refresh()
        if self.media_dialog and not self.media_dialog.closed:self.media_dialog.refresh()
        return 'break'

    def update_selection_label(self):
        if not self.trim:
            return
        kept = self.cuts.kept_duration(self.trim)
        removed = self.cuts.removed_duration(self.trim)
        if removed > .0005:
            self.selection_label.configure(
                text=f'Selected {format_time(self.trim.duration)}  ·  '
                     f'After cuts {format_time(kept)}  ·  Removed {format_time(removed)}'
            )
        else:
            self.selection_label.configure(
                text=f'Keeping {format_time(self.trim.duration)}  ·  Drag the cyan handles to adjust.'
            )

    def update_trim(self, trim):
        trim.validate(self.media)
        self.cuts.validate_selection(self.media, trim)
        self.trim = trim
        self.start_text.set(format_time(trim.start))
        self.end_text.set(format_time(trim.end))
        self.update_selection_label()
        if hasattr(self, 'cut_tools'):
            self.cut_tools.refresh()
        self.note.configure(text='Ready to export. Your original recording stays untouched.', fg=t.MUTED)
        self.export_button.configure(state='normal')
        self.update_timeline()

    def cuts_changed(self, message):
        self.cuts.validate_selection(self.media, self.trim)
        self.stop_play()
        self.update_selection_label()
        self.cut_tools.refresh()
        self.update_timeline()
        self.export_button.configure(state='normal')
        self.note.configure(text=message, fg=t.MUTED)
        self.request_frame()

    def commit_entries(self):
        if not self.media or self.exporter.busy or self.closing:
            return False
        try:
            self.overlay_tools.commit_text()
            self.edits.validate(self.media)
            trim = TrimRange(parse_time(self.start_text.get()), parse_time(self.end_text.get()))
            self.update_trim(trim)
            return True
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)
            self.export_button.configure(state='disabled')
            return False

    def use_playhead(self, bound):
        self.stop_play()
        variable = self.start_text if bound == 'start' else self.end_text
        variable.set(format_time(self.position))
        self.commit_entries()

    def drag_trim(self, trim, bound):
        try:
            self.update_trim(trim)
            self.seek(trim.start if bound == 'start' else trim.end)
        except ValueError as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def reset_trim(self):
        self.update_trim(TrimRange(0, self.media.duration))
        self.seek(0)

    def _update_transport_controls(self):
        if not hasattr(self, 'play_button'):
            return
        ready = bool(self.media and not self.exporter.busy and not self.closing)
        self.play_button.configure(state='normal' if ready and not self.playing else 'disabled')
        self.pause_button.configure(state='normal' if ready and self.playing else 'disabled')
        self.stop_button.configure(state='normal' if ready else 'disabled')

    def toggle_audio(self):
        self.audio_toggle.configure(text='SOUND ON' if self.audio_on.get() else 'MUTED')
        resume=self.playing
        self.stop_play()
        if resume:self.play_preview()

    def play_preview(self):
        if self.playing or not self.commit_entries():
            return
        segments = self.cuts.kept_segments(self.trim)
        if not segments:
            return
        if self.position < self.trim.start or self.position >= self.trim.end:
            self.position = segments[0].start
        else:
            self.position = self.cuts.snap_position(self.position, self.trim)
            if self.position >= segments[-1].end - 1e-9:
                self.position = segments[0].start
        self.playing = True
        # Don't start audio while FFmpeg is still decoding the first displayed
        # frame. Otherwise the soundtrack races ahead of the *picture* during
        # preview startup, even if both streams share the same clock.
        self._waiting_for_play_frame = True
        self.play_anchor = self.position
        self.play_anchor_elapsed = self.cuts.source_elapsed(self.position, self.trim)
        self.play_started = time.monotonic()
        self._update_transport_controls()
        self.update_timeline()
        if self._seek_id:
            self.after_cancel(self._seek_id);self._seek_id=None
        self.token+=1
        self.playback.play(self.token,self.position,self.video.winfo_width()-4,
                           self.video.winfo_height()-4,self.edits,self.trim,self.cuts,
                           int(self.preview_quality.get()[:-1]))

    def pause_preview(self):
        if not self.playing:
            return
        # stop_play samples the audio clock before stopping the output device.
        self.stop_play()
        self.update_timeline()
        self.request_frame()

    def stop_preview(self):
        self.stop_play(reset=True)
        self.request_frame()

    def toggle_play(self):
        # Backward-compatible helper for any callers from older builds.
        if self.playing:
            self.pause_preview()
        else:
            self.play_preview()

    def _elapsed_kept(self):
        """Map the master audio clock onto the cut-aware source timeline."""
        if self._waiting_for_play_frame:return self.play_anchor_elapsed
        delta = time.monotonic() - self.play_started
        if (self.audio_on.get() and self.audio_player and
                (self.media.has_audio or self.edits.music.enabled or self.edits.sounds)):
            audio_delta = self.audio_player.elapsed()
            if audio_delta is None:
                # Wait for device/decoder startup: video must not get ahead.
                return self.play_anchor_elapsed
            delta = audio_delta
        return self.play_anchor_elapsed + max(0.0, delta) * self.edits.speed

    def stop_play(self, reset=False):
        if self.playing and self.trim:
            total = self.cuts.kept_duration(self.trim)
            elapsed = min(total, self._elapsed_kept())
            self.position = self.cuts.source_from_elapsed(elapsed, self.trim)
        if self.audio_player:
            self.audio_player.stop()
        if self.playback:self.playback.stop()
        self._waiting_for_play_frame = False
        self.playing = False
        if self._play_id:
            self.after_cancel(self._play_id)
            self._play_id = None
        if reset and self.trim:
            segments = self.cuts.kept_segments(self.trim)
            self.position = segments[0].start if segments else self.trim.start
        if self.media and self.trim:
            self.update_timeline()
        self._update_transport_controls()

    def next_frame(self):
        self._play_id = None
        if self.playing:
            total = self.cuts.kept_duration(self.trim)
            elapsed = min(total, self._elapsed_kept())
            self.position = self.cuts.source_from_elapsed(elapsed, self.trim)
            self.update_timeline()
            if elapsed >= total - 1e-9:
                self.playing = False
                if self.audio_player:
                    self.audio_player.stop()
                self._update_transport_controls()
            if not self.playing:self.request_frame()

    def poll_playback(self):
        if not self.playing or not self.playback:return
        if self.playback.error:
            message=self.playback.error
            self.stop_play();self.note.configure(text=message,fg=t.RED)
            return
        elapsed=min(self.cuts.kept_duration(self.trim),self._elapsed_kept())
        frame=self.playback.take_due(elapsed/self.edits.speed)
        if frame is not None and frame.token==self.token:
            self._photo=tk.PhotoImage(master=self,data=frame.ppm,format='PPM')
            self.video.itemconfigure('placeholder',text='')
            self.video.show_frame(self._photo,False,frame.edits,frame.position)
            if self._waiting_for_play_frame:
                self._waiting_for_play_frame=False
                self.play_started=time.monotonic()
                if self.audio_on.get() and self.audio_player:
                    self.audio_player.play(self.play_anchor,self.trim,self.cuts,self.edits)
            self.position=self.cuts.source_from_elapsed(elapsed,self.trim)
            self.update_timeline()
        if not self._waiting_for_play_frame and elapsed>=self.cuts.kept_duration(self.trim)-1e-9:
            self.stop_play()
            self.request_frame()

    def export(self):
        if (self.commentary_studio is not None and
                self.commentary_studio.recorder.active):
            self.note.configure(
                text='Stop and save commentary before exporting.',
                fg=t.RED)
            return
        if not self.overlay_tools.privacy_committed() or not self.commit_entries():
            return
        self.stop_play()
        try:
            self.exporter.start(self.media, self.trim, self.output_folder, self.edits, self.cuts)
            self.set_busy(True)
            self.progress['value'] = 0
            self.note.configure(text='Exporting your video…', fg=t.CYAN)
        except Exception as exc:
            self.note.configure(text=str(exc), fg=t.RED)

    def set_busy(self, busy):
        if busy and self.audio_player:
            self.audio_player.stop()
        self.audio_toggle.configure(state='disabled' if busy else 'normal')
        for widget in self.controls:
            widget.configure(state='disabled' if busy else 'normal')
        self.timeline.enabled = not busy
        self.video.enabled = not busy
        self.video.drag = None
        self.video.zoom_drag = False
        self.video.gesture = self.video.candidate = None
        self.video.media_drag = None
        self.update_brand_controls()
        self.cut_tools.refresh()
        self.overlay_tools.refresh()
        self.music_tools.refresh()
        self.polish_tools.refresh()
        if self.media:
            self.refresh_crop_guide()
        self._update_transport_controls()
        self.export_button.configure(state='disabled' if busy else 'normal',
                                     text='EXPORTING…' if busy else 'EXPORT VIDEO  ↗')
        if busy:
            self.cancel_button.configure(state='normal')
            self.cancel_button.pack(side='left', padx=(10, 0))
        else:
            self.cancel_button.pack_forget()

    def cancel_export(self):
        self.exporter.cancel()
        self.cancel_button.configure(state='disabled')
        self.note.configure(text='Cancelling export…', fg=t.MUTED)

    def change_folder(self):
        chosen = filedialog.askdirectory(parent=self, initialdir=self.output_folder, title='Save exported videos here')
        if chosen:
            self.output_folder = Path(chosen)
            self.destination.configure(text='Save new copy in: ' + self.output_folder.name)

    def open_folder(self):
        try:
            folder = self.last_export.parent if self.last_export else self.output_folder
            os.startfile(str(folder))
        except OSError as exc:
            self.note.configure(text=f'Could not open folder: {exc}', fg=t.RED)

    def poll(self):
        self._poll_id = None
        if self.closed:
            return
        try:
            media, error = self.metadata.get_nowait()
            if error:
                self.note.configure(text=error, fg=t.RED)
                self.video.itemconfigure('placeholder', text='Video unavailable')
            elif not self.closing:
                self.media = media
                self.video.media = media
                self.preview_note.configure(
                    text='Original + music audio preview' if media.has_audio
                    else 'No source audio · Add music to hear a soundtrack')
                self.preview = Preview(self.backend.ffmpeg, media)
                self.playback = PlaybackPreview(self.backend.ffmpeg, media)
                self.audio_player = AudioPlayback(self.backend.ffmpeg, media)
                self.update_trim(TrimRange(0, media.duration))
                self.set_busy(False)
                if self.auto_candidate:
                    try:
                        self.load_auto_candidate()
                    except ValueError as exc:
                        self.note.configure(text=f'Auto Edit plan could not be loaded: {exc}', fg=t.RED)
                        self.export_button.configure(state='disabled')
                if self.pulse_candidate:
                    try:
                        self.load_pulse_candidate()
                    except ValueError as exc:
                        self.note.configure(text=f'Pulse plan could not be loaded: {exc}', fg=t.RED)
                        self.export_button.configure(state='disabled')
                self.request_frame()
        except Empty:
            pass
        if self.audio_player:
            try:
                while True:
                    problem = self.audio_player.errors.get_nowait()
                    self.preview_note.configure(text='Audio preview unavailable', fg=t.RED)
                    self.note.configure(text=problem, fg=t.RED)
            except Empty:
                pass
        self.poll_playback()
        if self.preview:
            try:
                frame = self.preview.frames.get_nowait()
                if frame.token == self.token and not self.playing:
                    if frame.error:
                        self.stop_play()
                        self.video.delete('frame', 'crop', 'privacy', 'privacy-active', 'zoom', 'visual-guide')
                        self.video.photo = None
                        self.video.source_view = False
                        self.video.itemconfigure('placeholder', text='Preview unavailable')
                        self.note.configure(text=frame.error, fg=t.RED)
                    else:
                        self._photo = tk.PhotoImage(master=self, data=frame.ppm, format='PPM')
                        self.video.itemconfigure('placeholder', text='')
                        self.video.show_frame(self._photo, frame.source_view, frame.edits, frame.position)
            except Empty:
                pass
        try:
            while True:
                event = self.exporter.events.get_nowait()
                self.progress['value'] = event.progress
                if event.kind in ('progress', 'validating'):
                    self.note.configure(text=event.message or f'Exporting… {round(event.progress*100)}%', fg=t.CYAN)
                else:
                    self.set_busy(False)
                    if event.kind == 'saved':
                        self.last_export = event.path
                        warning = event.message if event.message != 'Export complete' else ''
                        summary = f'EXPORTED ✓  {event.path.name}'
                        if warning:
                            summary += ' — ' + warning
                        self.note.configure(text=summary, fg=t.CYAN if warning else t.GREEN)
                    else:
                        self.note.configure(text=event.message, fg=t.RED if event.kind == 'error' else t.MUTED)
        except Empty:
            pass
        if self.closing and not self.exporter.busy and not self.auto_children and not (
                self.auto_dialog and not self.auto_dialog.closed):
            self.finish_close()
            return
        self._poll_id = self.after(15 if self.playing else 60, self.poll)

    def close(self):
        if self.closed:
            return
        self.closing = True
        self.stop_play()
        if self.preview:
            self.preview.close()
        if self.playback:self.playback.close()
        if self.audio_player:
            self.audio_player.close()
        for child in list(self.auto_children):
            child.close()
        if self.auto_dialog and not self.auto_dialog.closed:
            self.auto_dialog.close()
        if self.commentary_studio is not None and self.commentary_studio.winfo_exists():
            self.commentary_studio.close()
        if self.exporter.busy:
            self.cancel_export()
        elif not self.auto_children and not (self.auto_dialog and not self.auto_dialog.closed):
            self.finish_close()

    def finish_close(self):
        if self.closed:
            return
        self.closed = True
        if self.preview:
            self.preview.close()
        if self.playback:self.playback.close()
        if self.audio_player:
            self.audio_player.close()
        for timer in (self._seek_id, self._poll_id, self._play_id):
            if timer:
                self.after_cancel(timer)
        self.destroy()
        if self.on_close:
            self.on_close(self)
