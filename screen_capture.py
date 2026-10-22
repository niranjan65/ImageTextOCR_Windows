"""Drag-to-select screen capture using Tkinter and Pillow."""

import ctypes
from ctypes import wintypes
import sys
import tkinter as tk
from typing import Callable

from PIL import Image, ImageGrab, ImageTk


def enable_dpi_awareness() -> None:
    """Keep Tk coordinates and captured pixels aligned on scaled Windows displays."""
    if sys.platform != "win32":
        return
    try:
        # Per-monitor awareness, available on Windows 10 and newer.
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()


def grab_desktop() -> tuple[Image.Image, tuple[int, int]]:
    image = ImageGrab.grab(all_screens=True, include_layered_windows=True)
    if sys.platform == "win32":
        user32 = ctypes.windll.user32
        return image, (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77))
    return image, (0, 0)


class ScreenCaptureOverlay(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        image: Image.Image,
        origin: tuple[int, int],
        on_complete: Callable[[Image.Image | None], None],
    ) -> None:
        super().__init__(master)
        self.withdraw()
        self.image = image
        self.on_complete = on_complete
        self.start: tuple[int, int] | None = None
        self.finished = False
        try:
            self.overrideredirect(True)
            self.attributes("-topmost", True)
            width, height = image.size
            self.geometry(f"{width}x{height}+0+0")
            self.canvas = tk.Canvas(self, highlightthickness=0, cursor="crosshair")
            self.canvas.pack(fill="both", expand=True)
            self.photo = ImageTk.PhotoImage(image, master=self)
            self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
            self.shades = [
                self.canvas.create_rectangle(0, 0, width, height, fill="black", stipple="gray50", outline="")
                for _ in range(4)
            ]
            self.outline = self.canvas.create_rectangle(0, 0, 0, 0, outline="#4da3ff", width=2)
            # Place instructions on the primary display even if another monitor is to its left.
            label_x, label_y = max(18, 18 - origin[0]), max(18, 18 - origin[1])
            self.canvas.create_rectangle(label_x, label_y, label_x + 440, label_y + 38, fill="#152d5c", outline="")
            self.canvas.create_text(
                label_x + 12, label_y + 19, anchor="w", fill="white",
                text="Drag to capture an area  |  Esc or right-click to cancel",
                font=("Segoe UI", 11),
            )
            self.canvas.bind("<ButtonPress-1>", self._press)
            self.canvas.bind("<B1-Motion>", self._drag)
            self.canvas.bind("<ButtonRelease-1>", self._release)
            self.bind("<Escape>", self._cancel)
            self.bind("<Button-3>", self._cancel)
            self.protocol("WM_DELETE_WINDOW", self._cancel)
            self.update_idletasks()
            self.deiconify()
            if sys.platform == "win32":
                # Tk's negative geometry offsets anchor to the right/bottom edge.
                # Use absolute Windows coordinates for monitors left of/above the primary.
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.GetParent.argtypes = [wintypes.HWND]
                user32.GetParent.restype = wintypes.HWND
                user32.SetWindowPos.argtypes = [
                    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                    ctypes.c_int, ctypes.c_int, wintypes.UINT,
                ]
                user32.SetWindowPos.restype = wintypes.BOOL
                handle = user32.GetParent(self.winfo_id()) or self.winfo_id()
                if not user32.SetWindowPos(handle, wintypes.HWND(-1), *origin, width, height, 0x0040):
                    raise ctypes.WinError(ctypes.get_last_error())
            self.lift()
            self.grab_set()
            self.focus_force()
        except Exception:
            self.destroy()
            raise

    def _point(self, event) -> tuple[int, int]:
        return max(0, min(event.x, self.image.width)), max(0, min(event.y, self.image.height))

    def _press(self, event) -> None:
        self.start = self._point(event)
        self._drag(event)

    def _drag(self, event) -> None:
        if self.start is None:
            return
        x, y = self._point(event)
        left, right = sorted((self.start[0], x))
        top, bottom = sorted((self.start[1], y))
        width, height = self.image.size
        for shade, box in zip(self.shades, (
            (0, 0, width, top), (0, bottom, width, height),
            (0, top, left, bottom), (right, top, width, bottom),
        )):
            self.canvas.coords(shade, *box)
        self.canvas.coords(self.outline, left, top, right, bottom)

    def _release(self, event) -> None:
        if self.start is None:
            return
        x, y = self._point(event)
        left, right = sorted((self.start[0], x))
        top, bottom = sorted((self.start[1], y))
        if right - left < 2 or bottom - top < 2:
            self.start = None
            return
        # Crop the original pixels, excluding shading, instructions, and outline.
        self._finish(self.image.crop((left, top, right, bottom)))

    def _cancel(self, _event=None) -> None:
        self._finish(None)

    def _finish(self, result: Image.Image | None) -> None:
        if self.finished:
            return
        self.finished = True
        self.destroy()
        self.on_complete(result)

    def destroy(self) -> None:
        if self.grab_current() == self:
            self.grab_release()
        super().destroy()
        self.image.close()
        self.photo = None
