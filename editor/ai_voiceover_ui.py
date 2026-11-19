"""Voiceover Studio UI: explicit consent, reusable WAVs, no network on open."""
import os
from pathlib import Path
from queue import Queue, Empty
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from ui import theme as t
from .ai_voiceover import SpeechRequest, STYLES, VOICES, generate, library_root


class VoiceoverStudio(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Pulse Capture · AI Voiceover Studio")
        self.configure(bg=t.BG)
        self.geometry("680x510")
        self.minsize(540, 430)
        self.transient(parent)
        self.events = Queue()
        self.busy = False
        self.saved = None
        t.label(self, "AI VOICEOVER STUDIO", 18, t.CYAN, True).pack(anchor="w", padx=20, pady=(18, 6))
        t.label(self, "Write narration, choose a style and generate a reusable local WAV.", 10, t.MUTED).pack(anchor="w", padx=20)
        self.script = tk.Text(self, height=8, wrap="word", bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN)
        self.script.pack(fill="both", expand=True, padx=20, pady=(12, 8))
        controls = tk.Frame(self, bg=t.BG)
        controls.pack(fill="x", padx=20)
        self.voice = tk.StringVar(value="marin")
        self.style = tk.StringVar(value="Dry British")
        t.label(controls, "Voice", 10).grid(row=0, column=0, sticky="w")
        self.voice_box = ttk.Combobox(controls, textvariable=self.voice, values=VOICES, state="readonly", width=13)
        self.voice_box.grid(row=0, column=1, padx=8)
        t.label(controls, "Delivery", 10).grid(row=0, column=2, padx=(10,0))
        self.style_box = ttk.Combobox(controls, textvariable=self.style, values=tuple(STYLES), state="readonly", width=20)
        self.style_box.grid(row=0, column=3, padx=8)
        keyrow = tk.Frame(self, bg=t.BG)
        keyrow.pack(fill="x", padx=20, pady=12)
        t.label(keyrow, "API key", 10).pack(side="left")
        self.key = tk.StringVar(value=os.environ.get("OPENAI_API_KEY", ""))
        self.key_entry = tk.Entry(keyrow, textvariable=self.key, show="•", width=42)
        self.key_entry.pack(side="left", padx=8, fill="x", expand=True)
        t.label(self, "Audio is generated only after confirmation. Each unique request is attempted once. "
                "Prices vary; this screen cannot guarantee a GBP charge. "
                "OpenAI has announced retirement of this speech endpoint on 6 Jan 2027.",
                9, t.MUTED, wraplength=635, justify="left").pack(anchor="w", padx=20)
        actions = tk.Frame(self, bg=t.BG)
        actions.pack(fill="x", padx=20, pady=12)
        self.make_button = t.button(actions, "GENERATE VOICE", self.make, accent=True)
        self.make_button.pack(side="left")
        self.listen_button = t.button(actions, "PLAY SAVED WAV", self.listen)
        self.listen_button.pack(side="left", padx=8)
        self.listen_button.configure(state="disabled")
        self.folder_button = t.button(actions, "OPEN LIBRARY", self.open_library)
        self.folder_button.pack(side="right")
        self.status = t.label(self, "No API request sent.", 10, t.MUTED, wraplength=635)
        self.status.pack(fill="x", padx=20, pady=(0, 14))
        self.after(100, self.poll)
        self.protocol("WM_DELETE_WINDOW", self.close)

    def make(self):
        if self.busy:
            return
        try:
            req = SpeechRequest(self.script.get("1.0", "end-1c"), self.voice.get(), self.style.get())
            req.validate()
        except ValueError as exc:
            self.status.configure(text=str(exc), fg=t.RED)
            return
        existing = library_root() / (req.identity + ".wav")
        if not existing.exists():
            if not messagebox.askyesno("Confirm paid OpenAI request",
                 "This will make ONE chargeable OpenAI speech-generation request. "
                 "Actual price depends on API billing and may not be known beforehand. "
                 "There is no automatic retry. Spend API credits?", parent=self):
                self.status.configure(text="Cancelled. No request sent.", fg=t.MUTED)
                return
        key = self.key.get()
        self.busy = True
        self.make_button.configure(state="disabled")
        self.status.configure(text="Loading saved narration…" if existing.exists() else "Generating voiceover…", fg=t.CYAN)

        def worker():
            try:
                path, reused = generate(req, approval=not existing.exists(), api_key=key)
                self.events.put((path, reused, None))
            except Exception as exc:
                self.events.put((None, False, str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        try:
            while True:
                path, reused, error = self.events.get_nowait()
                self.busy = False
                self.make_button.configure(state="normal")
                if error:
                    self.status.configure(text=error, fg=t.RED)
                else:
                    self.saved = Path(path)
                    self.listen_button.configure(state="normal")
                    self.status.configure(text=("Reused saved audio (free): " if reused else
                                                "Generated and saved: ") + str(self.saved), fg=t.GREEN)
        except Empty:
            pass
        if self.winfo_exists():
            self.after(100, self.poll)

    def listen(self):
        if self.saved and self.saved.is_file():
            try:
                import winsound
                winsound.PlaySound(str(self.saved), winsound.SND_FILENAME | winsound.SND_ASYNC)
            except (ImportError, RuntimeError, OSError):
                self.status.configure(text="Could not play WAV through Windows audio.", fg=t.RED)

    def open_library(self):
        folder = library_root()
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(str(folder))

    def close(self):
        # The background request may still finish and be charged; no retries.
        self.key.set("")
        self.destroy()
