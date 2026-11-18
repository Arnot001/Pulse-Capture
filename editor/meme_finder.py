"""Native in-app audio discovery panel. Search, preview and import stay inside Quick Edit."""
import hashlib
from pathlib import Path
from queue import Empty, Queue
import tempfile
import threading
import tkinter as tk
from tkinter import messagebox
import webbrowser

from ui import theme as t
from .media_audition import Audition
from .meme_catalog import fetch_audio, search_openverse


class MemeFinder(tk.Toplevel):
    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.title("FIND MEME SOUNDS — OPEN AUDIO")
        self.geometry("790x570")
        self.minsize(680, 480)
        self.configure(bg=t.BG)
        self.transient(dialog)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.closed = False
        self.busy = False
        self.cancel = threading.Event()
        self.events = Queue()
        self.results = []
        self.temp = tempfile.TemporaryDirectory(prefix="pulse-meme-finder-")
        self.after_id = None
        self.search_text = tk.StringVar(value=dialog.search.get().strip() or "funny reaction")
        head = tk.Frame(self, bg=t.BG)
        head.pack(fill="x", padx=15, pady=12)
        t.label(head, "Sound search", 11, t.TEXT, True).pack(side="left", padx=(0, 8))
        entry = tk.Entry(head, textvariable=self.search_text, width=36, bg=t.CONTROL,
                         fg=t.TEXT, insertbackground=t.TEXT, relief="flat")
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self.search())
        t.button(head, "SEARCH", self.search, accent=True).pack(side="left", padx=(8, 0))

        t.label(self, "Made using Openverse (independent; not endorsed). CC0 / Public Domain / CC BY.",
                9, t.MUTED).pack(anchor="w", padx=15, pady=(0, 8))
        centre = tk.Frame(self, bg=t.BG)
        centre.pack(fill="both", expand=True, padx=15)
        left = tk.Frame(centre, bg=t.BG)
        left.pack(side="left", fill="both", expand=True)
        self.listbox = tk.Listbox(left, bg=t.CONTROL, fg=t.TEXT,
                                 selectbackground=t.LINE, selectforeground=t.TEXT,
                                 relief="flat", exportselection=False, activestyle="none")
        self.listbox.pack(side="left", fill="both", expand=True)
        scroll = tk.Scrollbar(left, command=self.listbox.yview)
        scroll.pack(side="left", fill="y")
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.bind("<<ListboxSelect>>", self.selected_changed)
        self.details = t.label(centre, "Choose a result to see its licence and creator.",
                               10, t.TEXT, anchor="nw", justify="left", wraplength=255)
        self.details.configure(bg=t.PANEL, width=32, padx=14, pady=14)
        self.details.pack(side="right", fill="y", padx=(10, 0))

        actions = tk.Frame(self, bg=t.BG)
        actions.pack(fill="x", padx=15, pady=(12, 5))
        t.button(actions, "▶ PREVIEW", self.preview).pack(side="left")
        t.button(actions, "STOP", self.stop).pack(side="left", padx=6)
        t.button(actions, "SOURCE / RIGHTS", self.source).pack(side="left")
        t.button(actions, "IMPORT TO LIBRARY", self.import_selected, accent=True).pack(side="right")
        self.note = t.label(self, "Select a result, preview it, then import if you have the rights. "
                            "Imported clips appear in SOUND FX for timeline insertion.",
                            9, t.MUTED, wraplength=745, justify="left")
        self.note.pack(fill="x", padx=15, pady=(7, 12))
        self.audition = Audition(self, self.report)
        self.after_id = self.after(80, self.poll)
        entry.focus_set()
        # Opening the finder is an explicit search action; never background-crawl.
        self.search()

    def report(self, message, error=False):
        if not self.closed:
            self.note.configure(text=message, fg=t.RED if error else t.CYAN)

    def chosen(self):
        selection = self.listbox.curselection()
        if len(selection) != 1 or selection[0] >= len(self.results):
            raise ValueError("Select one sound first.")
        return self.results[selection[0]]

    def selected_changed(self, _event=None):
        try:
            item = self.chosen()
            self.details.configure(text=(item["name"] + "\n\nCreator: " + item["creator"] +
                "\n\nIndexed licence: " + item["license"] +
                "\n\nCheck the source before publishing. Search index metadata is not a licence grant."))
        except ValueError:
            pass

    def start_job(self, operation, item=None):
        if self.busy or self.closed:
            return
        self.busy = True
        self.report({"search": "Searching open audio…", "preview": "Loading selected sound…",
                     "import": "Importing the selected clip…"}[operation])
        phrase = self.search_text.get()
        folder = Path(self.temp.name)
        library = self.dialog.library
        backend = self.dialog.window.backend

        def run():
            try:
                if operation == "search":
                    value = search_openverse(phrase)
                else:
                    name = hashlib.sha256(item["id"].encode("utf-8")).hexdigest()[:20] + item["suffix"]
                    path = folder / name
                    if not path.is_file():
                        fetch_audio(item, path, cancelled=self.cancel)
                    if self.cancel.is_set():
                        raise ValueError("Sound request cancelled.")
                    if operation == "preview":
                        value = path
                    else:
                        old_ids = {asset["id"] for asset in library.items("sfx") if asset["id"].startswith("import.")}
                        key = library.import_file(path, "sfx", backend.ffmpeg, backend.ffprobe)
                        if key not in old_ids:
                            details = dict(name=item["name"], artist=item["creator"],
                                           source=item["source"] or "Openverse search result",
                                           licence="Openverse index: " + item["license"] +
                                                   " (unverified; inspect original source)",
                                           attribution=item["attribution"])
                            library.update_details(key, details)
                        value = key
                if not self.closed:
                    self.events.put((operation, value, None))
            except Exception as exc:
                if not self.closed:
                    self.events.put((operation, None, str(exc)))
            finally:
                # Close can occur during slow network access. The worker owns the
                # temporary files until its final operation completes.
                if self.closed:
                    self.temp.cleanup()
        threading.Thread(target=run, daemon=True, name="Pulse open audio search").start()

    def search(self):
        self.stop()
        self.start_job("search")

    def preview(self):
        try:
            self.stop()
            self.start_job("preview", self.chosen())
        except ValueError as exc:
            self.report(str(exc), True)

    def import_selected(self):
        try:
            item = self.chosen()
        except ValueError as exc:
            self.report(str(exc), True)
            return
        if self.busy:
            return
        if not messagebox.askyesno("Check audio rights",
            "Openverse lists this recording as " + item["license"] +
            ". The index may be wrong.\n\nOnly use it in published videos if you have"
            " checked permission and any attribution requirements.\n\nImport to"
            " your local library marked Unverified?", parent=self):
            return
        self.start_job("import", item)

    def source(self):
        try:
            link = self.chosen()["source"]
            if not link:
                raise ValueError("No source page was supplied for this sound.")
            webbrowser.open(link)
        except ValueError as exc:
            self.report(str(exc), True)

    def stop(self):
        self.audition.stop()

    def poll(self):
        if self.closed:
            return
        try:
            while True:
                operation, value, error = self.events.get_nowait()
                self.busy = False
                if error:
                    self.report(error, True)
                elif operation == "search":
                    self.results = value
                    self.listbox.delete(0, "end")
                    for item in value:
                        self.listbox.insert("end", item["name"] + "  ·  " + item["license"])
                    self.report(f"Found {len(value)} supported open-audio results. "
                                "Search another phrase if none fit.")
                elif operation == "preview":
                    ffmpeg = self.dialog.window.backend.ffmpeg
                    self.audition.play(lambda output: [str(ffmpeg), "-v", "error", "-nostdin", "-n",
                        "-i", str(value), "-ac", "2", "-ar", "48000",
                        "-c:a", "pcm_s16le", str(output)])
                elif operation == "import":
                    dialog = self.dialog
                    dialog.audio_scope.set("All audio")
                    dialog.search.set("")
                    dialog.category.set("All")
                    dialog.refresh_library()
                    if dialog.assets.exists(value):
                        dialog.assets.selection_set(value)
                        dialog.assets.see(value)
                    self.report("Imported into SOUND FX (rights Unverified). Close finder and "
                                "click INSERT AT PLAYHEAD in the soundboard.")
        except Empty:
            pass
        self.after_id = self.after(80, self.poll)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.cancel.set()
        if self.after_id is not None:
            self.after_cancel(self.after_id)
        self.audition.close()
        if not self.busy:
            self.temp.cleanup()
        self.destroy()
