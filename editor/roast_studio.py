"""Dedicated JSON Roast Studio workflow; rendering is still Pulse Plan v2.

The original recipe is never overwritten. The selected Quick Edit video is the
only source. A review prompt is mandatory when a different file is being used.
"""
from pathlib import Path
from queue import Empty, Queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from ui import theme as t
from .pulse_plan import read_pulse_plan, source_identity
from .roast_recipe import bind_roast_recipe, inspect_coverage, reference_mismatch


class RoastStudioDialog(tk.Toplevel):
    def __init__(self, window):
        if window.media is None:
            raise ValueError("Choose a video in Quick Edit first.")
        super().__init__(window)
        self.window = window
        self.media = window.media
        self.closed = self.busy = False
        self.cancel = threading.Event()
        self.events = Queue()
        self.plan = None
        self.path = None
        self.poll_id = None
        self.title("PULSE // ROAST STUDIO — JSON EDITOR")
        self.geometry("690x490")
        self.minsize(630, 450)
        self.configure(bg=t.BG)
        self.transient(window)
        self.protocol("WM_DELETE_WINDOW", self.close)

        t.label(self, "ROAST STUDIO", 20, t.CYAN, True).pack(anchor="w", padx=22, pady=(18, 5))
        t.label(self, "Import a JSON comedy edit. Pick the actual recording in Quick Edit first.",
                10, t.TEXT, wraplength=630, justify="left").pack(anchor="w", padx=22)
        t.label(self, "SOURCE / OPEN VIDEO", 9, t.CYAN, True).pack(anchor="w", padx=22, pady=(19, 3))
        t.label(self, self.media.path.name, 11, t.TEXT,
                wraplength=630, justify="left").pack(anchor="w", padx=22)
        self.media_label = t.label(self, f"{self.media.duration:.3f}s  ·  {self.media.width} × "
                                   f"{self.media.height}  ·  {self.media.fps:g} FPS",
                                   9, t.MUTED)
        self.media_label.pack(anchor="w", padx=22, pady=(4, 10))

        row = tk.Frame(self, bg=t.BG)
        row.pack(fill="x", padx=22, pady=6)
        t.button(row, "CHOOSE JSON EDIT", self.load, accent=True).pack(side="left")
        self.recipe_label = t.label(row, "No JSON selected", 9, t.MUTED,
                                    wraplength=420, justify="left")
        self.recipe_label.pack(side="left", padx=(12, 0), fill="x", expand=True)

        offset_row = tk.Frame(self, bg=t.BG)
        offset_row.pack(fill="x", padx=22, pady=(14, 4))
        t.label(offset_row, "SOURCE OFFSET (seconds)", 10, t.TEXT, True).pack(side="left")
        self.offset = tk.StringVar(value="0")
        tk.Entry(offset_row, textvariable=self.offset, width=12,
                 bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN,
                 relief="flat").pack(side="left", padx=12)
        t.label(self, "Keep 0 if the scene is at the same timestamp. For a trimmed copy, "
                "shift the source timestamps by the difference (e.g. -180 moves 03:00 to 00:00). "
                "This DOES NOT identify scenes automatically.",
                9, t.MUTED, wraplength=630, justify="left").pack(anchor="w", padx=22, pady=5)
        t.label(self, "CAPTIONS: LOCKED TO TOP/BOTTOM DARK BANDS",
                10, t.CYAN, True).pack(anchor="w", padx=22, pady=(14, 3))
        t.label(self, "No captions over gameplay. Existing Pulse v2 effects, freezes, zooms, "
                "emoji/GIF and imported audio IDs are preserved and checked. "
                "Unrecognised sound assets are not substituted.",
                9, t.MUTED, wraplength=630, justify="left").pack(anchor="w", padx=22)
        self.status = t.label(self, "Choose a Pulse Edit Plan v2 JSON to begin.",
                              10, t.MUTED, wraplength=630, justify="left")
        self.status.pack(anchor="w", padx=22, pady=(14, 6))

        buttons = tk.Frame(self, bg=t.BG)
        buttons.pack(fill="x", padx=22, pady=(8, 16))
        self.go_button = t.button(buttons, "BUILD & REVIEW ROAST", self.build, accent=True)
        self.go_button.configure(state="disabled")
        self.go_button.pack(side="left")
        t.button(buttons, "CLOSE", self.close).pack(side="right")
        self.poll_id = self.after(80, self.poll)

    def status_text(self, message, error=False):
        if not self.closed:
            self.status.configure(text=message, fg=t.RED if error else t.CYAN)

    def load(self):
        if self.busy:
            return
        path = filedialog.askopenfilename(parent=self, title="Import a JSON comedy edit",
                                          filetypes=[("Pulse Edit Plan v2", "*.json")])
        if not path:
            return
        try:
            plan = read_pulse_plan(path)
            if plan.get("version") != 2:
                raise ValueError("Use a Pulse Edit Plan v2 JSON with timed captions and effects.")
            # This checks source timelines without pretending the files are identical.
            inspect_coverage(plan, self.media, float(self.offset.get().strip()))
            self.plan, self.path = plan, Path(path)
            self.recipe_label.configure(text=self.path.name, fg=t.TEXT)
            self.status_text("JSON loaded. Build a new preview bound to the open recording.")
            self.go_button.configure(state="normal")
        except (ValueError, OSError, TypeError) as exc:
            self.plan = self.path = None
            self.recipe_label.configure(text="No valid JSON selected", fg=t.MUTED)
            self.go_button.configure(state="disabled")
            self.status_text(str(exc), True)

    def build(self):
        if self.busy or self.plan is None:
            return
        try:
            offset = float(self.offset.get().strip())
            offset = inspect_coverage(self.plan, self.media, offset)
        except (ValueError, TypeError) as exc:
            self.status_text(str(exc), True)
            return

        self.busy = True
        self.go_button.configure(state="disabled")
        self.status_text("Checking the open recording's SHA-256 fingerprint…")
        plan, media = self.plan, self.media

        def work():
            try:
                identity = source_identity(media, self.cancel)
                self.events.put(("identity", identity, offset))
            except Exception as exc:
                self.events.put(("error", str(exc), offset))
        threading.Thread(target=work, daemon=True,
                         name="Pulse Roast Studio source verification").start()

    def poll(self):
        self.poll_id = None
        if self.closed:
            return
        try:
            while True:
                kind, payload, offset = self.events.get_nowait()
                self.busy = False
                self.go_button.configure(state="normal" if self.plan else "disabled")
                if kind == "error":
                    self.status_text(payload, True)
                    continue
                identity = payload
                mismatches = reference_mismatch(self.plan, identity)
                if mismatches:
                    label = ", ".join(mismatches)
                    warning = (
                        "THIS IS NOT THE SAME VERIFIED SOURCE AS THE JSON.\n\n"
                        f"Different: {label}\n"
                        f"JSON reference duration: {self.plan['source']['duration']:.3f}s\n"
                        f"Opened video duration: {self.media.duration:.3f}s\n"
                        f"Source time adjustment: {offset:+.3f}s\n\n"
                        "Only proceed if you have checked that the scene occurs at "
                        "those times in this video. The wrong copy can produce a "
                        "perfectly valid but completely unrelated edit.\n\n"
                        "Bind this JSON to the selected video and review the result?")
                    if not messagebox.askyesno("Review different source footage",
                                               warning, parent=self):
                        self.status_text("No changes made. Use the matching footage or set Source offset.")
                        continue
                try:
                    rebound = bind_roast_recipe(
                        self.plan, self.media, identity, offset=offset,
                        confirm_mismatch=bool(mismatches), captions_in_bands=True)
                    from .pulse_tools import open_plan_dialog
                    dialog = open_plan_dialog(self.window, plan=rebound, media=self.media)
                    self.status_text("Recipe bound. Rendering a new editable review — original untouched.")
                    self.close()
                    dialog.render()
                    return
                except (ValueError, OSError, tk.TclError) as exc:
                    self.status_text(str(exc), True)
        except Empty:
            pass
        self.poll_id = self.after(80, self.poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel.set()
        if self.poll_id:
            self.after_cancel(self.poll_id)
        self.window.auto_children.discard(self)
        self.destroy()
