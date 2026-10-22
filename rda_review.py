"""Review, correct, explicitly omit and export mapped RDA fields."""
import json
from pathlib import Path
import webbrowser
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from rda_mapping import load_schema, normalize_value


class VerificationDetailsDialog(tk.Toplevel):
    """Show mismatches while retaining the identity of the created record."""
    def __init__(self, parent, failure):
        super().__init__(parent)
        self.title('Saved record verification details')
        self.geometry('850x420')
        self.transient(parent)
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=f'Record {failure.saved.name} was created. Check its saved values before sending again.', wraplength=800).pack(anchor='w', pady=(0, 12))
        self.tree = ttk.Treeview(frame, columns=('expected', 'stored'), show='tree headings')
        self.tree.heading('#0', text='Field')
        self.tree.heading('expected', text='Expected')
        self.tree.heading('stored', text='Stored')
        self.tree.pack(fill='both', expand=True)
        for key, mismatch in failure.mismatches.items():
            if isinstance(mismatch, dict):
                values = (str(mismatch.get('expected')), str(mismatch.get('actual')))
            else:
                values = ('Read-back verification', str(mismatch))
            self.tree.insert('', 'end', iid=key, text=key, values=values)
        ttk.Button(frame, text='Open Created Record', command=lambda: webbrowser.open(failure.saved.url)).pack(anchor='e', pady=(12, 0))


class RDAReviewDialog(tk.Toplevel):
    def __init__(self, master, mapping, on_send):
        super().__init__(master)
        self.title('Review RDA fields before sending')
        self.geometry('910x650')
        self.transient(master)
        self.on_send = on_send
        self.payload = dict(mapping.payload)
        self.issues = list(mapping.issues)
        self.fields = {f['fieldname']: f for f in load_schema()['fields']}
        self._sent = False
        self.fieldname = tk.StringVar()
        self.value = tk.StringVar()
        self.omit = tk.BooleanVar()
        self.status = tk.StringVar()
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill='both', expand=True)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text='Each send creates a new record. Captured values can be sent directly; edits are optional.', wraplength=850).grid(row=0, column=0, sticky='w', pady=(0, 8))
        self.tree = ttk.Treeview(frame, columns=('value', 'status'), show='tree headings')
        self.tree.heading('#0', text='DocType field')
        self.tree.heading('value', text='Current value')
        self.tree.heading('status', text='Status')
        self.tree.column('#0', width=245)
        self.tree.column('value', width=270)
        self.tree.column('status', width=320)
        self.tree.grid(row=1, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(frame, orient='vertical', command=self.tree.yview)
        scrollbar.grid(row=1, column=1, sticky='ns')
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.bind('<<TreeviewSelect>>', self._select)
        editor = ttk.Frame(frame)
        editor.grid(row=2, column=0, sticky='ew', pady=10)
        editor.columnconfigure(1, weight=1)
        ttk.Label(editor, textvariable=self.fieldname, width=30).grid(row=0, column=0, sticky='w')
        ttk.Entry(editor, textvariable=self.value).grid(row=0, column=1, sticky='ew', padx=5)
        ttk.Checkbutton(editor, text='Omit', variable=self.omit).grid(row=0, column=2)
        ttk.Button(editor, text='Apply', command=self._apply).grid(row=0, column=3, padx=5)
        ttk.Label(frame, textvariable=self.status, wraplength=850).grid(row=4, column=0, sticky='w', pady=8)
        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky='e')
        ttk.Button(buttons, text='Export JSON', command=self.export).pack(side='left', padx=8)
        self.send_btn = ttk.Button(buttons, text='Send New Record', command=self.send)
        self.send_btn.pack(side='left')
        self._refresh()

    def _refresh(self):
        self.tree.delete(*self.tree.get_children())
        for key in self.fields:
            status = 'Captured' if key in self.payload else 'Omitted'
            self.tree.insert('', 'end', iid=key, text=key, values=(self.payload.get(key, ''), status))
        self.status.set('Ready to send captured values. Editing is optional.')

    def _select(self, _event=None):
        selected = self.tree.selection()
        if selected:
            key = selected[0]
            self.fieldname.set(key)
            self.value.set(str(self.payload.get(key, '')))
            self.omit.set(key not in self.payload)

    def set_value(self, fieldname, value, omit=False):
        if fieldname not in self.fields:
            raise ValueError('Unknown DocType field')
        if omit:
            self.payload.pop(fieldname, None)
        else:
            try:
                normalized = normalize_value(value, self.fields[fieldname])
            except ValueError:
                normalized = value
            if normalized == '':
                raise ValueError('Choose Omit for a blank field.')
            self.payload[fieldname] = normalized
        self.issues = [i for i in self.issues if i.fieldname != fieldname]
        self._refresh()

    def _apply(self):
        try:
            self.set_value(self.fieldname.get(), self.value.get(), self.omit.get())
        except ValueError as error:
            self.status.set(str(error))

    def send(self):
        if self._sent:
            return
        self._sent = True
        self.send_btn.configure(state='disabled')
        accepted = self.on_send(dict(self.payload))
        if accepted is False:
            self._sent = False
            self.send_btn.configure(state='normal')
        else:
            self.destroy()

    def export(self):
        target = filedialog.asksaveasfilename(parent=self, title='Export mapped RDA JSON', defaultextension='.json', initialfile='rda_information.json', filetypes=[('JSON files', '*.json')])
        if target:
            try:
                Path(target).write_text(json.dumps(self.payload, indent=2, allow_nan=False) + '\n', encoding='utf-8')
                self.status.set('Mapped JSON exported.')
            except (OSError, ValueError):
                self.status.set('Could not export this JSON file.')
