"""ImageTextOCR desktop GUI. Build on Windows using build_windows.bat."""

from __future__ import annotations

from pathlib import Path
import os
import queue
import tempfile
import threading
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk, UnidentifiedImageError

from ocr_core import available_languages, extract_text, get_ocr_engine
from screen_capture import ScreenCaptureOverlay, enable_dpi_awareness, grab_desktop
import frappe_settings
from frappe_client import FrappeClient, FrappeError
from capture_workflow import CaptureJob, WorkflowEvent, run_capture_job, send_reviewed_job
from rda_review import RDAReviewDialog, VerificationDetailsDialog

APP_TITLE = "FedEx"
BG = "#f4f7fb"
INK = "#17263c"
MUTED = "#64748b"
BLUE = "#2159d3"
BORDER = "#dce4ee"


class OCRApp(tk.Tk):
    def __init__(self) -> None:
        enable_dpi_awareness()
        super().__init__()
        self.title(f"{APP_TITLE} - Image to Text")
        self.geometry("1140x710")
        self.minsize(890, 580)
        self.configure(bg=BG)

        self.selected_image: Path | None = None
        self.preview_image = None
        self.engine = None
        self._engine_state = 'pending'
        self.result_queue: queue.Queue = queue.Queue()
        result_queue = self.result_queue
        self._upload_sink = lambda event: result_queue.put(("upload", event))
        self.running = False
        self._capturing = False
        self._capture_overlay: ScreenCaptureOverlay | None = None
        self._capture_after: str | None = None
        self._capture_directory: tempfile.TemporaryDirectory | None = None
        self._capture_count = 0
        self._capture_window_state = "normal"
        self._closed = False
        self._frappe_client = None
        self._upload_job = None
        self._job_counter = 0
        self._terminal_jobs = set()
        self._mapping = None
        self._source_generation = 0
        self._review_dialog = None
        self._verification_failure = None
        self._details_dialog = None
        self._last_saved = None
        self._pending_upload = None
        self._open_review_when_ready = False
        self._save_uncertain = False
        self._connection_dialog = None
        preferences = frappe_settings.load_preferences()
        self._site_url = preferences['site_url']
        self.auto_send_var = tk.BooleanVar(value=preferences['auto_send'])
        self.connection_var = tk.StringVar(value="Not connected — configure Skylink to auto-send captures")
        self.language_var = tk.StringVar(value="eng")
        self.file_label_var = tk.StringVar(value="No image selected")
        self.status_var = tk.StringVar(value="Select an image to get started.")

        self._set_style()
        self._create_ui()
        self.after(90, self._drain_results)
        self.after(100, self._load_engine)
        # Optional process-local bootstrap; credentials are never read from source/config files.
        sid = os.environ.pop('SKYLINK_SESSION_ID', '')
        api_key = os.environ.pop('SKYLINK_API_KEY', '')
        api_secret = os.environ.pop('SKYLINK_API_SECRET', '')
        if api_key or api_secret or sid:
            site = os.environ.get('SKYLINK_SITE_URL', self._site_url)
            def connect():
                try:
                    client = FrappeClient(site, api_key=api_key, api_secret=api_secret) if api_key or api_secret else FrappeClient(site, sid)
                    result_queue.put(('connection', client, client.test_connection()))
                except Exception:
                    result_queue.put(('connection_error',))
            threading.Thread(target=connect, daemon=True).start()

    def _set_style(self) -> None:
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.style.configure("App.TFrame", background=BG)
        self.style.configure("Card.TFrame", background="#ffffff")
        self.style.configure(
            "Primary.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(18, 11),
            background=BLUE,
            foreground="white",
            borderwidth=0,
        )
        self.style.map(
            "Primary.TButton",
            background=[("pressed", "#1645ad"), ("active", "#1645ad"), ("disabled", "#b7c6dc")],
            foreground=[("disabled", "#f6f8fc")],
        )
        self.style.configure(
            "Secondary.TButton",
            font=("Segoe UI", 10),
            padding=(13, 10),
            background="#edf2fa",
            foreground=INK,
            bordercolor=BORDER,
            borderwidth=1,
        )
        self.style.map(
            "Secondary.TButton",
            background=[("active", "#e3eaf5"), ("disabled", "#f2f5fa")],
        )
        self.style.configure("Lang.TCombobox", padding=7, font=("Segoe UI", 10))

    def _create_ui(self) -> None:
        header = tk.Frame(self, bg="#152d5c", height=102)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(
            header,
            text=APP_TITLE,
            bg="#152d5c",
            fg="#ffffff",
            font=("Segoe UI", 23, "bold"),
        ).pack(anchor="w", padx=28, pady=(17, 0))
        tk.Label(
            header,
            text="Capture RDA data, recognize it locally, and save mapped values to Skylink",
            bg="#152d5c",
            fg="#bdcfe9",
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=30, pady=(0, 12))

        connection_bar = ttk.Frame(self, style="App.TFrame", padding=(20, 8))
        connection_bar.pack(fill="x")
        connection_bar.columnconfigure(0, weight=1)
        ttk.Label(connection_bar, textvariable=self.connection_var, wraplength=470).grid(row=0, column=0, sticky="w")
        self.auto_send_box = ttk.Checkbutton(connection_bar, text="Auto-send captures", variable=self.auto_send_var, command=self._save_preferences)
        self.auto_send_box.grid(row=0, column=1, padx=8)
        self.connection_btn = ttk.Button(connection_bar, text="Connection Settings", command=self._connection_settings)
        self.connection_btn.grid(row=0, column=2, padx=(4, 0))
        main = ttk.Frame(self, style="App.TFrame", padding=(20, 8, 20, 12))
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=5, uniform="panels")
        main.columnconfigure(1, weight=7, uniform="panels")
        main.rowconfigure(0, weight=1)

        left = tk.Frame(main, bg="white", highlightbackground=BORDER, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(3, weight=1)

        tk.Label(
            left, text="SOURCE IMAGE", bg="white", fg=INK,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(19, 9))

        controls = tk.Frame(left, bg="white")
        controls.grid(row=1, column=0, sticky="ew", padx=18)
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        self.upload_btn = ttk.Button(
            controls, text="Browse image...", command=self._browse_image,
            style="Primary.TButton",
        )
        self.upload_btn.grid(row=0, column=0, sticky="ew")
        self.capture_btn = ttk.Button(
            controls, text="Capture Screenshot", command=self._capture_screen,
            style="Secondary.TButton",
        )
        self.capture_btn.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        controls.bind("<Configure>", self._layout_source_controls)
        tk.Label(
            left, text="PNG  JPG  BMP  TIFF  WEBP  |  Capture any screen area", bg="white", fg=MUTED,
            font=("Segoe UI", 9), wraplength=300, justify="left",
        ).grid(row=2, column=0, sticky="w", padx=20, pady=(7, 0))

        self.preview_container = tk.Frame(left, bg="#f5f8fc", highlightthickness=1, highlightbackground=BORDER)
        self.preview_container.grid(row=3, column=0, sticky="nsew", padx=18, pady=(13, 13))
        self.preview_container.grid_propagate(False)
        self.preview_label = tk.Label(
            self.preview_container,
            text="Your image preview will appear here",
            bg="#f5f8fc", fg=MUTED,
            font=("Segoe UI", 11), wraplength=250,
        )
        self.preview_label.pack(fill="both", expand=True, padx=15, pady=15)
        self.preview_container.bind("<Configure>", self._on_preview_resize)

        tk.Label(
            left, textvariable=self.file_label_var,
            bg="white", fg=MUTED, font=("Segoe UI", 9),
            anchor="w", wraplength=400,
        ).grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 17))

        right = tk.Frame(main, bg="white", highlightbackground=BORDER, highlightthickness=1)
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        top = tk.Frame(right, bg="white")
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 9))
        tk.Label(
            top, text="EXTRACTED TEXT", bg="white", fg=INK,
            font=("Segoe UI", 10, "bold"),
        ).pack(side="left")
        tk.Label(top, text="Language", bg="white", fg=MUTED, font=("Segoe UI", 9)).pack(side="right", padx=(8, 0))
        self.language_box = ttk.Combobox(
            top, width=11, state="readonly", textvariable=self.language_var,
            values=["eng"], style="Lang.TCombobox",
        )
        self.language_box.pack(side="right", padx=9)

        info = tk.Label(
            right,
            text="Recognized text is editable. Review results before relying on them.",
            bg="white", fg=MUTED, font=("Segoe UI", 9), anchor="w", wraplength=400, justify="left",
        )
        info.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))

        text_area = tk.Frame(right, bg="white")
        text_area.grid(row=2, column=0, sticky="nsew", padx=20)
        text_area.rowconfigure(0, weight=1)
        text_area.columnconfigure(0, weight=1)
        self.output_text = tk.Text(
            text_area,
            wrap="word",
            undo=True,
            bg="#f9fbff",
            fg=INK,
            insertbackground=INK,
            relief="flat",
            borderwidth=0,
            padx=14,
            pady=14,
            font=("Consolas", 11),
            highlightbackground=BORDER,
            highlightcolor="#6b99e8",
            highlightthickness=1,
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(text_area, orient="vertical", command=self.output_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.output_text.configure(yscrollcommand=scrollbar.set)

        action_row = tk.Frame(right, bg="white")
        action_row.grid(row=3, column=0, sticky="ew", padx=20, pady=17)
        self.extract_btn = ttk.Button(
            action_row, text="Extract Text", command=self._extract,
            style="Primary.TButton", state="disabled",
        )
        self.extract_btn.pack(side="left", padx=(0, 10))
        self.copy_btn = ttk.Button(action_row, text="Copy Text", command=self._copy, style="Secondary.TButton")
        self.copy_btn.pack(side="left", padx=(0, 8))
        self.save_btn = ttk.Button(action_row, text="Save .txt", command=self._save, style="Secondary.TButton")
        self.save_btn.pack(side="left")
        self._update_result_buttons()

        upload_row = tk.Frame(right, bg="white")
        upload_row.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 12))
        self.review_btn = ttk.Button(upload_row, text="Review & Send RDA", command=self._review_and_send, state="disabled")
        self.review_btn.pack(side="left")
        self.open_record_btn = ttk.Button(upload_row, text="Open Saved Record", command=self._open_saved_record, state="disabled")
        self.open_record_btn.pack(side="left", padx=8)
        self.error_details_btn = ttk.Button(upload_row, text="Save Details", command=self._show_save_details, state="disabled")
        self.error_details_btn.pack(side="left")

        bottom = tk.Frame(self, bg="#ecf1f7", height=54)
        bottom.pack(side="bottom", fill="x", before=main)
        bottom.pack_propagate(False)
        status_label = tk.Label(
            bottom, textvariable=self.status_var, bg="#ecf1f7", fg="#46617f",
            font=("Segoe UI", 9), anchor="w", justify="left", wraplength=650,
        )
        status_label.pack(side="left", fill="x", expand=True, padx=26)
        status_label.bind('<Configure>', lambda event: status_label.configure(wraplength=max(100, event.width)))
        tk.Label(
            bottom, text="Local OCR • Mapped values sent to configured site", bg="#ecf1f7",
            fg=MUTED, font=("Segoe UI", 9),
        ).pack(side="right", padx=26)

    def _layout_source_controls(self, event) -> None:
        needed = self.upload_btn.winfo_reqwidth() + self.capture_btn.winfo_reqwidth() + 8
        if event.width < needed:
            self.upload_btn.grid_configure(row=0, column=0, columnspan=2)
            self.capture_btn.grid_configure(row=1, column=0, columnspan=2, padx=0, pady=(8, 0))
        else:
            self.upload_btn.grid_configure(row=0, column=0, columnspan=1)
            self.capture_btn.grid_configure(row=0, column=1, columnspan=1, padx=(8, 0), pady=0)

    def _load_engine(self) -> None:
        # Engine discovery can invoke subprocesses; keep the UI responsive.
        self._engine_state = 'pending'
        result_queue = self.result_queue
        def work() -> None:
            try:
                tool = get_ocr_engine()
                langs = available_languages(tool)
                result_queue.put(("engine", tool, langs))
            except Exception as exc:
                result_queue.put(("engine_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()
        self.status_var.set("Checking OCR engine...")

    def _browse_image(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select image to extract text from",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            with Image.open(selected) as image:
                image.verify()
        except (OSError, UnidentifiedImageError) as exc:
            messagebox.showerror("Invalid image", f"Unable to open this file as an image.\n\n{exc}")
            return
        self._select_image(Path(selected))

    def _select_image(self, path: Path) -> None:
        self._source_generation += 1
        for dialog in (self._review_dialog, self._details_dialog):
            if dialog is not None and dialog.winfo_exists():
                dialog.destroy()
        self._review_dialog = None
        self._details_dialog = None
        self._verification_failure = None
        self.error_details_btn.configure(state="disabled")
        self._open_review_when_ready = False
        if self._upload_job is not None:
            self._upload_job.cancelled.set()
        self._upload_job = None
        self._mapping = None
        self._last_saved = None
        self._save_uncertain = False
        self._pending_upload = None
        self._terminal_jobs.clear()
        self.review_btn.configure(state="normal")
        self.open_record_btn.configure(state="disabled")
        self.selected_image = path
        self.file_label_var.set(self.selected_image.name)
        self.output_text.delete("1.0", "end")
        self._update_result_buttons()
        self._update_preview()
        self.status_var.set(f"Ready to extract text: {self.selected_image.name}")
        self.extract_btn.configure(state="normal" if self.engine is not None and not self.running else "disabled")

    def _capture_screen(self) -> None:
        if self.running or self._capturing:
            return
        self._capturing = True
        self._capture_window_state = self.state()
        self.capture_btn.configure(state="disabled")
        self.upload_btn.configure(state="disabled")
        self.extract_btn.configure(state="disabled")
        self.status_var.set("Drag to select a screen area. Press Esc to cancel.")
        self.withdraw()
        # Let Windows repaint the desktop so this app is excluded from the capture.
        self._capture_after = self.after(300, self._show_capture_overlay)

    def _show_capture_overlay(self) -> None:
        self._capture_after = None
        try:
            image, origin = grab_desktop()
            self._capture_overlay = ScreenCaptureOverlay(self, image, origin, self._complete_capture)
        except Exception as exc:
            self._restore_after_capture()
            self.status_var.set("Screen capture failed.")
            messagebox.showerror("Capture failed", f"Unable to capture the screen.\n\n{exc}")

    def _restore_after_capture(self) -> None:
        self._capture_overlay = None
        self._capturing = False
        self.deiconify()
        if self._capture_window_state == "zoomed":
            self.state("zoomed")
        self.lift()
        self.capture_btn.configure(state="normal")
        self.upload_btn.configure(state="normal")
        self.extract_btn.configure(
            state="normal" if self.selected_image and self.engine is not None and not self.running else "disabled"
        )

    def _complete_capture(self, image: Image.Image | None) -> None:
        if self._closed:
            if image is not None:
                image.close()
            return
        self._restore_after_capture()
        if image is None:
            self.status_var.set("Screen capture cancelled.")
            return
        try:
            if self._capture_directory is None:
                self._capture_directory = tempfile.TemporaryDirectory(prefix="ImageTextOCR_")
            self._capture_count += 1
            path = Path(self._capture_directory.name) / f"screenshot_{self._capture_count}.png"
            image.save(path, format="PNG")
            self._select_image(path)
            self.file_label_var.set(f"Screenshot ({image.width} x {image.height})")
            self.status_var.set("Screenshot captured. Click Extract Text.")
            if self._frappe_client is not None and self.auto_send_var.get():
                self._start_capture_upload(auto_send=True)
        except Exception as exc:
            self.status_var.set("Screen capture failed.")
            messagebox.showerror("Capture failed", f"Unable to load the screenshot.\n\n{exc}")
        finally:
            image.close()

    def _on_preview_resize(self, _event=None) -> None:
        if self.selected_image:
            # Tk's geometry manager needs a paint pass before width/height are final.
            if not self.running:
                self.after_idle(self._update_preview)

    def _update_preview(self) -> None:
        if self.selected_image is None:
            return
        width = max(120, self.preview_container.winfo_width() - 35)
        height = max(120, self.preview_container.winfo_height() - 35)
        try:
            with Image.open(self.selected_image) as source:
                preview = ImageOps.exif_transpose(source).convert("RGB")
                preview.thumbnail((width, height), Image.Resampling.LANCZOS)
            self.preview_image = ImageTk.PhotoImage(preview)
            self.preview_label.configure(image=self.preview_image, text="")
        except Exception as exc:
            self.preview_label.configure(image="", text=f"Unable to preview image: {exc}")

    def _extract(self) -> None:
        if self.selected_image is None or self.engine is None or self.running or self._capturing:
            return
        path = self.selected_image
        language = self.language_var.get()
        self.running = True
        self._set_upload_busy(True)
        self.extract_btn.configure(state="disabled")
        self.upload_btn.configure(state="disabled")
        self.capture_btn.configure(state="disabled")
        self.status_var.set("Extracting text from image...")
        tool = self.engine
        result_queue = self.result_queue

        def work() -> None:
            try:
                text = extract_text(path, language, tool=tool)
                result_queue.put(("text", text))
            except Exception as exc:
                result_queue.put(("ocr_error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _drain_results(self) -> None:
        try:
            while True:
                result = self.result_queue.get_nowait()
                kind = result[0]
                if kind == "engine":
                    self.engine = result[1]
                    langs = result[2]
                    if not langs:
                        self.engine = None
                        self._engine_state = 'failed'
                        self._pending_upload = None
                        self._set_upload_busy(False)
                        self.status_var.set("OCR engine found, but no languages are installed.")
                        messagebox.showwarning("No language data", "Tesseract has no installed language models (for example eng.traineddata).")
                    else:
                        self._engine_state = 'ready'
                        self.language_box.configure(values=langs)
                        self.language_var.set("eng" if "eng" in langs else langs[0])
                        self.status_var.set("OCR ready. Select an image and click Extract Text.")
                        if self.selected_image and not self.running and not self._capturing:
                            self.extract_btn.configure(state="normal")
                        if self._pending_upload is not None:
                            auto_send = self._pending_upload
                            self._pending_upload = None
                            self._start_capture_upload(auto_send)
                elif kind == "engine_error":
                    self.engine = None
                    self._engine_state = 'failed'
                    if self._pending_upload is not None:
                        self._pending_upload = None
                        self._set_upload_busy(False)
                    self.status_var.set("OCR engine not available.")
                    messagebox.showerror("OCR engine missing", result[1])
                elif kind == "text":
                    self.running = False
                    self._set_upload_busy(False)
                    text = result[1]
                    self.output_text.delete("1.0", "end")
                    self.output_text.insert("1.0", text)
                    self.status_var.set(
                        f"Extracted {len(text):,} characters."
                        if text else "No text detected. Try a sharper or higher-resolution image."
                    )
                    self.extract_btn.configure(state="normal")
                    self.upload_btn.configure(state="normal")
                    self.capture_btn.configure(state="normal")
                    self._update_result_buttons()
                elif kind == "ocr_error":
                    self.running = False
                    self._set_upload_busy(False)
                    self.extract_btn.configure(state="normal")
                    self.upload_btn.configure(state="normal")
                    self.capture_btn.configure(state="normal")
                    self.status_var.set("Text extraction failed.")
                    messagebox.showerror("OCR failed", result[1])
                elif kind == "upload":
                    self._handle_upload_event(result[1])
                elif kind == "connection":
                    self._on_connected(result[1], result[2])
                elif kind == "connection_error":
                    self.connection_var.set("Connection failed — check API credentials in Connection Settings")
        except queue.Empty:
            pass
        if not self._closed:
            self.after(100, self._drain_results)

    def _save_preferences(self):
        try:
            frappe_settings.save_preferences(self._site_url, self.auto_send_var.get())
        except OSError:
            self.status_var.set("Settings apply for this session; preferences could not be saved.")

    def _connection_settings(self):
        if self.running:
            return
        if self._connection_dialog is not None and self._connection_dialog.winfo_exists():
            self._connection_dialog.lift()
            return
        self._connection_dialog = frappe_settings.ConnectionDialog(self, self._on_connected)

    def _on_connected(self, client, connection):
        self._frappe_client = client
        self._site_url = client.base_url
        self.connection_var.set(f"{connection.user} • {client.base_url} • {'API' if client.auth_mode == 'api' else 'Session'}")
        self._save_preferences()
        self.status_var.set("Connected. Each auto-sent capture creates a new RDA Information record.")

    def _set_upload_busy(self, busy):
        self.running = busy
        state = "disabled" if busy else "normal"
        for button in (self.capture_btn, self.upload_btn, self.connection_btn, self.auto_send_box):
            button.configure(state=state)
        self.extract_btn.configure(state="normal" if not busy and self.selected_image and self.engine is not None else "disabled")
        self.review_btn.configure(state="normal" if not busy and self.selected_image else "disabled")

    def _start_capture_upload(self, auto_send):
        if self._closed or self.selected_image is None:
            return
        self._set_upload_busy(True)
        if self.engine is None:
            if self._engine_state == 'failed':
                self._pending_upload = None
                self._set_upload_busy(False)
                self.status_var.set("OCR is unavailable. Install Tesseract language data and restart the app before processing captures.")
                return
            self._pending_upload = auto_send
            self.status_var.set("Waiting for the OCR engine before processing this capture...")
            return
        self._job_counter += 1
        self._terminal_jobs.clear()
        job = CaptureJob(self._job_counter, self.selected_image, self.language_var.get(), auto_send)
        self._upload_job = job
        self.status_var.set("Recognizing and mapping RDA fields...")
        threading.Thread(target=run_capture_job, args=(job, self.engine, self._frappe_client, self._upload_sink), daemon=True).start()

    def _handle_upload_event(self, event):
        if self._closed or self._upload_job is None or event.job_id != self._upload_job.job_id or event.job_id in self._terminal_jobs:
            return
        if event.phase == "ocr":
            self.output_text.delete("1.0", "end")
            self.output_text.insert("1.0", event.data)
            self._update_result_buttons()
        elif event.phase == "mapped":
            self._mapping = event.data
        elif event.phase == "sending":
            self.status_var.set("Creating a new RDA Information record and verifying saved fields...")
        elif event.phase in ("verified", "failed", "review_required", "outcome_unknown", "verification_failed"):
            self._terminal_jobs.add(event.job_id)
            self._set_upload_busy(False)
            if event.phase == "verified":
                self._last_saved = event.data
                self.open_record_btn.configure(state="normal")
                self.status_var.set(f"Saved and verified {len(event.data.submitted)-1} fields: {event.data.name}")
            elif event.phase == "review_required":
                self.status_var.set("Captured values are ready. Use Review & Send RDA to send or optionally edit them.")
                if self._open_review_when_ready:
                    self._open_review_when_ready = False
                    self._open_review()
            else:
                self._save_uncertain = event.phase in ("outcome_unknown", "verification_failed")
                if event.phase == "verification_failed":
                    self._last_saved = event.data.saved
                    self._verification_failure = event.data
                    self.error_details_btn.configure(state="normal")
                    self.open_record_btn.configure(state="normal")
                self.status_var.set(str(event.data))

    def _review_and_send(self):
        if self.running or self.selected_image is None:
            return
        if self._mapping is None:
            self._open_review_when_ready = True
            self._start_capture_upload(auto_send=False)
        else:
            self._open_review()

    def _open_review(self):
        if self._mapping is not None:
            if self._review_dialog is not None and self._review_dialog.winfo_exists():
                self._review_dialog.lift()
                return
            generation = self._source_generation
            self._review_dialog = RDAReviewDialog(self, self._mapping, lambda payload: self._send_reviewed(payload, generation))

    def _send_reviewed(self, payload, generation=None):
        if self.running or self._closed:
            return False
        if self._mapping is None or (generation is not None and generation != self._source_generation):
            self.status_var.set("The source image changed. Review the current image before sending.")
            return False
        if self._frappe_client is None:
            self.status_var.set("Connect to Skylink before sending. Your mapped values are retained.")
            self._connection_settings()
            return False
        self._job_counter += 1
        self._terminal_jobs.clear()
        self._upload_job = CaptureJob(self._job_counter, self.selected_image, self.language_var.get(), False)
        self._mapping.payload = dict(payload)
        self._mapping.issues.clear()
        self._set_upload_busy(True)
        threading.Thread(target=send_reviewed_job, args=(self._upload_job, payload, self._frappe_client, self._upload_sink), daemon=True).start()
        return True

    def _open_saved_record(self):
        if self._last_saved is not None:
            webbrowser.open(self._last_saved.url)

    def _show_save_details(self):
        if self._verification_failure is not None:
            if self._details_dialog is not None and self._details_dialog.winfo_exists():
                self._details_dialog.lift()
                return
            self._details_dialog = VerificationDetailsDialog(self, self._verification_failure)

    def _update_result_buttons(self) -> None:
        has_text = bool(self.output_text.get("1.0", "end-1c").strip())
        state = "normal" if has_text else "disabled"
        self.copy_btn.configure(state=state)
        self.save_btn.configure(state=state)

    def _copy(self) -> None:
        content = self.output_text.get("1.0", "end-1c")
        if not content.strip():
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.status_var.set("Text copied to clipboard.")

    def _save(self) -> None:
        content = self.output_text.get("1.0", "end-1c")
        if not content.strip():
            return
        proposed = f"{self.selected_image.stem}_ocr.txt" if self.selected_image else "ocr_output.txt"
        target = filedialog.asksaveasfilename(
            title="Save extracted text",
            defaultextension=".txt",
            initialfile=proposed,
            filetypes=[("Text files", "*.txt")],
        )
        if not target:
            return
        try:
            Path(target).write_text(content, encoding="utf-8-sig")
            self.status_var.set(f"Saved text to {target}")
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))

    def destroy(self) -> None:
        self._closed = True
        if self._upload_job is not None:
            self._upload_job.cancelled.set()
        if self._capture_after is not None:
            self.after_cancel(self._capture_after)
            self._capture_after = None
        if self._capture_overlay is not None:
            self._capture_overlay.destroy()
            self._capture_overlay = None
        super().destroy()
        if self._capture_directory is not None:
            self._capture_directory.cleanup()


if __name__ == "__main__":
    app = OCRApp()
    app.mainloop()
