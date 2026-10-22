"""ImageTextOCR desktop GUI. Build on Windows using build_windows.bat."""

from __future__ import annotations

from pathlib import Path
import queue
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageOps, ImageTk, UnidentifiedImageError

from ocr_core import available_languages, extract_text, get_ocr_engine
from screen_capture import ScreenCaptureOverlay, enable_dpi_awareness, grab_desktop

APP_TITLE = "ImageTextOCR"
BG = "#f4f7fb"
INK = "#17263c"
MUTED = "#64748b"
BLUE = "#2159d3"
BORDER = "#dce4ee"


class OCRApp(tk.Tk):
    def __init__(self) -> None:
        enable_dpi_awareness()
        super().__init__()
        self.title("ImageTextOCR - Image to Text")
        self.geometry("1140x710")
        self.minsize(890, 580)
        self.configure(bg=BG)

        self.selected_image: Path | None = None
        self.preview_image = None
        self.engine = None
        self.result_queue: queue.Queue = queue.Queue()
        self.running = False
        self._capturing = False
        self._capture_overlay: ScreenCaptureOverlay | None = None
        self._capture_after: str | None = None
        self._capture_directory: tempfile.TemporaryDirectory | None = None
        self._capture_count = 0
        self._capture_window_state = "normal"
        self.language_var = tk.StringVar(value="eng")
        self.file_label_var = tk.StringVar(value="No image selected")
        self.status_var = tk.StringVar(value="Select an image to get started.")

        self._set_style()
        self._create_ui()
        self.after(90, self._drain_results)
        self.after(100, self._load_engine)

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
            text="ImageTextOCR",
            bg="#152d5c",
            fg="#ffffff",
            font=("Segoe UI", 23, "bold"),
        ).pack(anchor="w", padx=28, pady=(17, 0))
        tk.Label(
            header,
            text="Choose an image or capture your screen to extract editable text  |  Works offline",
            bg="#152d5c",
            fg="#bdcfe9",
            font=("Segoe UI", 10),
        ).pack(anchor="w", padx=30, pady=(0, 12))

        main = ttk.Frame(self, style="App.TFrame", padding=20)
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

        bottom = tk.Frame(self, bg="#ecf1f7", height=38)
        bottom.pack(side="bottom", fill="x", before=main)
        bottom.pack_propagate(False)
        tk.Label(
            bottom, textvariable=self.status_var, bg="#ecf1f7", fg="#46617f",
            font=("Segoe UI", 9), anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=26)
        tk.Label(
            bottom, text="Local OCR  •  No upload to server", bg="#ecf1f7",
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
        def work() -> None:
            try:
                tool = get_ocr_engine()
                langs = available_languages(tool)
                self.result_queue.put(("engine", tool, langs))
            except Exception as exc:
                self.result_queue.put(("engine_error", str(exc)))

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
        self.extract_btn.configure(state="disabled")
        self.upload_btn.configure(state="disabled")
        self.capture_btn.configure(state="disabled")
        self.status_var.set("Extracting text from image...")

        def work() -> None:
            try:
                text = extract_text(path, language, tool=self.engine)
                self.result_queue.put(("text", text))
            except Exception as exc:
                self.result_queue.put(("ocr_error", str(exc)))

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
                        self.status_var.set("OCR engine found, but no languages are installed.")
                        messagebox.showwarning("No language data", "Tesseract has no installed language models (for example eng.traineddata).")
                    else:
                        self.language_box.configure(values=langs)
                        self.language_var.set("eng" if "eng" in langs else langs[0])
                        self.status_var.set("OCR ready. Select an image and click Extract Text.")
                        if self.selected_image and not self.running and not self._capturing:
                            self.extract_btn.configure(state="normal")
                elif kind == "engine_error":
                    self.status_var.set("OCR engine not available.")
                    messagebox.showerror("OCR engine missing", result[1])
                elif kind == "text":
                    self.running = False
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
                    self.extract_btn.configure(state="normal")
                    self.upload_btn.configure(state="normal")
                    self.capture_btn.configure(state="normal")
                    self.status_var.set("Text extraction failed.")
                    messagebox.showerror("OCR failed", result[1])
        except queue.Empty:
            pass
        self.after(100, self._drain_results)

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
