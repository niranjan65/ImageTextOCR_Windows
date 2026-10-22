"""Desktop integration tests using a generated screen image, not the user's desktop."""

from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
import gc
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont, ImageTk

from ocr_app import OCRApp
from ocr_core import get_ocr_engine
from screen_capture import ScreenCaptureOverlay


class ScreenCaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.previous_image = Path(self.directory.name) / "previous.png"
        Image.new("RGB", (40, 30), "green").save(self.previous_image)
        with patch.object(OCRApp, "_load_engine", lambda app: None):
            self.app = OCRApp()
        self.app.engine = object()
        self.app.update()
        with patch("ocr_app.filedialog.askopenfilename", return_value=str(self.previous_image)):
            self.app.upload_btn.invoke()
        self.app.output_text.insert("1.0", "Previous OCR result")
        self.app._update_result_buttons()
        self.screen = Image.new("RGB", (640, 300), "white")
        ImageDraw.Draw(self.screen).rectangle((40, 50, 159, 129), fill="red")

    def tearDown(self):
        if self.app is not None:
            # Cancel queued Tcl callbacks before disposing this test's interpreter.
            for task in self.app.tk.splitlist(self.app.tk.call("after", "info")):
                self.app.after_cancel(task)
            self.app.destroy()
            self.app = None
            gc.collect()
        self.screen.close()
        self.directory.cleanup()

    def wait_for(self, predicate, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("Timed out waiting for capture/OCR to finish")

    def start_capture(self, error=None):
        button = getattr(self.app, "capture_btn", None)
        self.assertIsNotNone(button, "The source panel needs a Capture Screenshot button")
        # Screen capture is the external boundary; keep the selector and app real.
        with patch("PIL.ImageGrab.grab", side_effect=error, return_value=self.screen.copy()):
            button.invoke()
            self.assertEqual(self.app.state(), "withdrawn")
            self.wait_for(lambda: getattr(self.app, "_capture_overlay", None) is not None
                          or self.app.state() != "withdrawn")
        return self.app._capture_overlay

    def select(self, overlay, start, end):
        overlay.canvas.event_generate("<ButtonPress-1>", x=start[0], y=start[1])
        overlay.canvas.event_generate("<B1-Motion>", x=end[0], y=end[1])
        overlay.canvas.event_generate("<ButtonRelease-1>", x=end[0], y=end[1])
        self.app.update()

    def test_drag_loads_exact_crop_and_clears_old_ocr(self):
        overlay = self.start_capture()
        self.select(overlay, (40, 50), (160, 130))
        self.assertNotEqual(self.app.state(), "withdrawn")
        self.assertIsNone(self.app._capture_overlay)
        with Image.open(self.app.selected_image) as captured:
            self.assertEqual(captured.size, (120, 80))
            self.assertEqual(captured.getpixel((0, 0)), (255, 0, 0))
            self.assertEqual(captured.getpixel((119, 79)), (255, 0, 0))
        self.assertEqual(self.app.output_text.get("1.0", "end-1c"), "")
        self.assertEqual(str(self.app.extract_btn["state"]), "normal")
        self.assertIsNotNone(self.app.preview_image)

    def test_capture_button_fits_default_and_minimum_window_sizes(self):
        self.assertIsNotNone(getattr(self.app, "capture_btn", None))
        for size in ("1140x710", "890x580"):
            with self.subTest(size=size):
                self.app.geometry(size)
                self.app.update()
                button = self.app.capture_btn
                parent = button.master
                self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
                self.assertLessEqual(button.winfo_x() + button.winfo_width(), parent.winfo_width())

    def test_reverse_drag_selects_same_pixels(self):
        overlay = self.start_capture()
        self.select(overlay, (160, 130), (40, 50))
        with Image.open(self.app.selected_image) as captured:
            self.assertEqual(captured.size, (120, 80))
            self.assertEqual(captured.getpixel((60, 40)), (255, 0, 0))

    def test_drag_outside_screen_is_clipped_to_image(self):
        overlay = self.start_capture()
        self.select(overlay, (40, 50), (700, 350))
        with Image.open(self.app.selected_image) as captured:
            self.assertEqual(captured.size, (600, 250))
            self.assertEqual(captured.getpixel((0, 0)), (255, 0, 0))

    def test_escape_preserves_previous_image_and_text(self):
        overlay = self.start_capture()
        overlay.event_generate("<Escape>")
        self.app.update()
        self.assertIsNone(self.app._capture_overlay)
        self.assertNotEqual(self.app.state(), "withdrawn")
        self.assertEqual(self.app.selected_image, self.previous_image)
        self.assertEqual(self.app.output_text.get("1.0", "end-1c"), "Previous OCR result")
        self.assertEqual(str(self.app.capture_btn["state"]), "normal")

    def test_empty_selection_can_be_retried(self):
        overlay = self.start_capture()
        self.select(overlay, (70, 70), (70, 70))
        self.assertIs(self.app._capture_overlay, overlay)
        self.assertEqual(self.app.selected_image, self.previous_image)
        self.select(overlay, (40, 50), (160, 130))
        with Image.open(self.app.selected_image) as captured:
            self.assertEqual(captured.size, (120, 80))

    def test_right_click_cancels_selection(self):
        overlay = self.start_capture()
        overlay.canvas.event_generate("<Button-3>", x=80, y=80)
        self.app.update()
        self.assertIsNone(self.app._capture_overlay)
        self.assertEqual(self.app.selected_image, self.previous_image)

    def test_png_write_failure_preserves_previous_source(self):
        overlay = self.start_capture()
        with patch("PIL.Image.Image.save", side_effect=OSError("Disk full")), patch("ocr_app.messagebox.showerror"):
            self.select(overlay, (40, 50), (160, 130))
        self.assertEqual(self.app.selected_image, self.previous_image)
        self.assertNotEqual(self.app.state(), "withdrawn")
        self.assertEqual(str(self.app.capture_btn["state"]), "normal")
        self.assertIn("failed", self.app.status_var.get().lower())

    def test_capture_failure_restores_usable_app(self):
        with patch("ocr_app.messagebox.showerror"):
            overlay = self.start_capture(OSError("Screen capture unavailable"))
        self.assertIsNone(overlay)
        self.assertNotEqual(self.app.state(), "withdrawn")
        self.assertEqual(self.app.selected_image, self.previous_image)
        self.assertEqual(str(self.app.capture_btn["state"]), "normal")
        self.assertIn("failed", self.app.status_var.get().lower())

    def test_captured_png_is_removed_when_app_closes(self):
        overlay = self.start_capture()
        self.select(overlay, (40, 50), (160, 130))
        captured_path = self.app.selected_image
        self.assertTrue(captured_path.is_file())
        for task in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.after_cancel(task)
        self.app.destroy()
        self.app = None
        self.assertFalse(captured_path.exists())

    def test_close_cancels_pending_capture_timer(self):
        self.assertIsNotNone(getattr(self.app, "capture_btn", None))
        self.app.capture_btn.invoke()
        pending = self.app._capture_after
        interpreter = self.app.tk
        for task in interpreter.splitlist(interpreter.call("after", "info")):
            if task != pending:
                self.app.after_cancel(task)
        self.app.destroy()
        self.app = None
        self.assertNotIn(pending, interpreter.splitlist(interpreter.call("after", "info")))

    def test_close_disposes_active_selector_and_its_mouse_grab(self):
        overlay = self.start_capture()
        self.assertIs(overlay.grab_current(), overlay)
        for task in self.app.tk.splitlist(self.app.tk.call("after", "info")):
            self.app.after_cancel(task)
        self.app.destroy()
        self.app = None
        with self.assertRaises(ValueError):
            overlay.image.getpixel((0, 0))

    def test_negative_desktop_origin_places_overlay_at_absolute_position(self):
        results = []
        overlay = ScreenCaptureOverlay(self.app, self.screen.copy(), (-640, -300), results.append)
        try:
            self.app.update()
            self.assertEqual((overlay.canvas.winfo_rootx(), overlay.canvas.winfo_rooty()), (-640, -300))
            overlay.canvas.event_generate("<ButtonPress-1>", x=40, y=50)
            overlay.canvas.event_generate("<ButtonRelease-1>", x=160, y=130)
            self.assertEqual(results[0].size, (120, 80))
            self.assertEqual(results[0].getpixel((60, 40)), (255, 0, 0))
        finally:
            if not overlay.finished:
                overlay.destroy()
            for image in results:
                image.close()

    def test_captured_image_runs_through_real_ocr(self):
        try:
            self.app.engine = get_ocr_engine()
        except RuntimeError as error:
            self.skipTest(str(error))
        self.screen.paste("white", (0, 0, 640, 300))
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 40)
        ImageDraw.Draw(self.screen).text((30, 60), "CAPTURE 12345", font=font, fill="black")
        overlay = self.start_capture()
        self.select(overlay, (10, 30), (550, 150))
        self.app.extract_btn.invoke()
        self.assertEqual(str(self.app.capture_btn["state"]), "disabled")
        self.wait_for(lambda: not self.app.running, timeout=10)
        self.assertIn("CAPTURE 12345", self.app.output_text.get("1.0", "end-1c"))
        self.assertEqual(str(self.app.capture_btn["state"]), "normal")

    def test_real_desktop_capture_preserves_calibration_pixels(self):
        self.assertIsNotNone(getattr(self.app, "capture_btn", None), "Capture Screenshot button missing")
        marker_image = Image.new("RGB", (260, 140), "#11cc77")
        ImageDraw.Draw(marker_image).rectangle((70, 40, 179, 99), fill="#cc2244")
        marker = tk.Toplevel(self.app)
        marker.overrideredirect(True)
        marker.geometry("260x140+100+200")
        marker.attributes("-topmost", True)
        photo = ImageTk.PhotoImage(marker_image, master=marker)
        canvas = tk.Canvas(marker, width=260, height=140, highlightthickness=0)
        canvas.pack()
        canvas.create_image(0, 0, image=photo, anchor="nw")
        self.app.update()
        x, y = canvas.winfo_rootx(), canvas.winfo_rooty()
        try:
            # Exercise the real ImageGrab boundary against only our calibration window.
            self.app.capture_btn.invoke()
            self.wait_for(lambda: self.app._capture_overlay is not None)
            overlay = self.app._capture_overlay
            left, top = x - overlay.canvas.winfo_rootx(), y - overlay.canvas.winfo_rooty()
            self.select(overlay, (left, top), (left + 260, top + 140))
            with Image.open(self.app.selected_image) as captured:
                self.assertEqual(captured.size, (260, 140))
                self.assertEqual(captured.getpixel((15, 15)), (17, 204, 119))
                self.assertEqual(captured.getpixel((100, 60)), (204, 34, 68))
        finally:
            marker.destroy()
            marker_image.close()


if __name__ == "__main__":
    unittest.main()
