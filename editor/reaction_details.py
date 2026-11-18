"""Searchable reaction descriptions and exact user-supplied rights information."""
import tkinter as tk
from tkinter import ttk
from ui import theme as t
from .soundboard import RIGHTS_STATUSES, rights_label


class ReactionDetails(tk.Toplevel):
    def __init__(self, dialog, asset_id):
        super().__init__(dialog)
        self.dialog, self.asset_id = dialog, asset_id
        item = dialog.library.metadata(asset_id)
        self.title('Reaction details & licence')
        self.geometry('640x710'); self.configure(bg=t.BG)
        self.transient(dialog); self.grab_set()
        self.values = {}
        editable = asset_id.startswith('import.')
        for key, label in (('name','Reaction name'), ('transcript','Spoken words / search terms'),
                           ('aliases','Aliases (e.g. nope, disbelief, nah)'), ('tags','Tags'),
                           ('artist','Performer / creator'), ('source','Source / licence page'),
                           ('licence','Licence supplied by the rights holder'), ('attribution','Exact attribution')):
            t.label(self, label, 10).pack(anchor='w', padx=16, pady=(8,2))
            entry = tk.Text(self, height=3 if key=='attribution' else 2 if key=='transcript' else 1,
                            bg=t.CONTROL, fg=t.TEXT, insertbackground=t.CYAN, wrap='word')
            entry.pack(fill='x', padx=16)
            entry.insert('1.0', item.get(key, ''))
            if not editable: entry.configure(state='disabled')
            self.values[key] = entry
        t.label(self, 'Rights status (your confirmation)', 10).pack(anchor='w', padx=16, pady=(8,2))
        self.rights = tk.StringVar(value=rights_label(item))
        ttk.Combobox(self, textvariable=self.rights, values=RIGHTS_STATUSES,
                     state='readonly' if editable else 'disabled').pack(fill='x', padx=16)
        self.note = t.label(self, 'Copy the supplied licence/credit exactly. A file tag is not proof of permission.',
                            9, t.MUTED, wraplength=600)
        self.note.pack(fill='x', padx=16, pady=10)
        row = tk.Frame(self, bg=t.BG); row.pack(fill='x', padx=16)
        if editable: t.button(row, 'SAVE DETAILS', self.save).pack(side='left')
        t.button(row, 'COPY CREDIT', self.copy_credit).pack(side='left', padx=8)
        t.button(row, 'DONE', self.destroy).pack(side='right')

    def copy_credit(self):
        credit = self.values['attribution'].get('1.0','end-1c')
        self.clipboard_clear(); self.clipboard_append(credit)
        self.note.configure(text='Copied the supplied attribution.', fg=t.GREEN)

    def save(self):
        try:
            values = {key:widget.get('1.0','end-1c') for key,widget in self.values.items()}
            values['rights_status'] = self.rights.get()
            self.dialog.library.update_details(self.asset_id, values)
            self.dialog.refresh_library()
            if self.dialog.assets.exists(self.asset_id): self.dialog.assets.selection_set(self.asset_id)
            self.note.configure(text='Saved name, search text and rights information. Audio is unchanged.', fg=t.GREEN)
        except (ValueError,OSError) as exc:
            self.note.configure(text=str(exc), fg=t.RED)
