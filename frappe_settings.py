"""Connection UI and non-secret application preferences."""
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk

from frappe_client import DEFAULT_SITE, FrappeClient, FrappeError


def _preference_path():
    return Path(os.environ.get('LOCALAPPDATA', Path.home() / '.config')) / 'ImageTextOCR' / 'preferences.json'


def load_preferences():
    try:
        data = json.loads(_preference_path().read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('Preferences must be an object')
        return {'site_url': str(data.get('site_url', DEFAULT_SITE)), 'auto_send': bool(data.get('auto_send', True))}
    except (OSError, ValueError, TypeError):
        return {'site_url': DEFAULT_SITE, 'auto_send': True}


def save_preferences(site_url, auto_send):
    path = _preference_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'site_url': site_url, 'auto_send': bool(auto_send)}, indent=2), encoding='utf-8')
    temporary.replace(path)


class ConnectionDialog(tk.Toplevel):
    def __init__(self, master, on_connected):
        super().__init__(master)
        self.title('Skylink Connection Settings')
        self.geometry('590x340')
        self.resizable(False, False)
        self.transient(master)
        self.on_connected = on_connected
        self.results = queue.Queue()
        self._closed = False
        self._poll_id = None
        self.site = tk.StringVar(value=getattr(master, '_site_url', DEFAULT_SITE))
        self.api_key = tk.StringVar()
        self.api_secret = tk.StringVar()
        self.status = tk.StringVar(value='Enter the API key and API secret for your ERPNext user.')
        frame = ttk.Frame(self, padding=20)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(1, weight=1)
        for row, (label, variable, masked) in enumerate([('Site URL', self.site, False), ('API Key', self.api_key, True), ('API Secret', self.api_secret, True)]):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky='w', padx=(0, 12), pady=8)
            ttk.Entry(frame, textvariable=variable, show='*' if masked else '').grid(row=row, column=1, sticky='ew', pady=8)
        ttk.Label(frame, text='API credentials stay in memory for this app session.', wraplength=500).grid(row=3, column=0, columnspan=2, sticky='w', pady=8)
        ttk.Label(frame, textvariable=self.status, wraplength=510).grid(row=4, column=0, columnspan=2, sticky='w', pady=8)
        self.test_btn = ttk.Button(frame, text='Test Connection & Apply', command=self.test_connection)
        self.test_btn.grid(row=5, column=0, columnspan=2, sticky='e', pady=8)
        self.protocol('WM_DELETE_WINDOW', self.destroy)

    def test_connection(self):
        try:
            client = FrappeClient(self.site.get(), api_key=self.api_key.get(), api_secret=self.api_secret.get())
        except FrappeError as error:
            self.status.set(str(error))
            return
        self.test_btn.configure(state='disabled')
        self.status.set('Testing API authentication and RDA Information access...')
        results = self.results
        def work():
            try:
                results.put((client, client.test_connection(), None))
            except FrappeError as error:
                results.put((None, None, str(error)))
            except Exception:
                results.put((None, None, 'Connection failed. Check the site and API credentials.'))
        threading.Thread(target=work, daemon=True).start()
        self._poll_id = self.after(100, self._poll)

    def _poll(self):
        self._poll_id = None
        if self._closed:
            return
        try:
            client, connection, error = self.results.get_nowait()
        except queue.Empty:
            self._poll_id = self.after(100, self._poll)
            return
        self.test_btn.configure(state='normal')
        if error:
            self.status.set(error)
        else:
            self.on_connected(client, connection)
            self.destroy()

    def destroy(self):
        self._closed = True
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
        self.api_key.set('')
        self.api_secret.set('')
        super().destroy()
