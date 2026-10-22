"""OCR engine adapter for ImageTextOCR, powered by PyOCR + Tesseract."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from PIL import Image, ImageOps


def configure_tesseract() -> None:
    """Make the bundled Windows Tesseract engine discoverable by PyOCR.

    `build_windows.bat` embeds tesseract.exe, its DLLs, and tessdata in the
    `tesseract` subdirectory of the PyInstaller extraction folder.
    """
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled = bundle_root / "tesseract"
    if (bundled / "tesseract.exe").is_file():
        os.environ["PATH"] = str(bundled) + os.pathsep + os.environ.get("PATH", "")
        # The Tesseract 5 CLI expects the parent of the tessdata directory.
        os.environ["TESSDATA_PREFIX"] = str(bundled)
        return

    if sys.platform != "win32":
        return

    # Make the source script work on Windows even if the installer didn't
    # add Tesseract to PATH. The final one-file exe uses the bundled copy.
    candidates = [
        Path(os.environ.get("TESSERACT_HOME", "")),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR",
    ]
    for folder in candidates:
        if (folder / "tesseract.exe").is_file():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
            return


def get_ocr_engine():
    """Discover an OCR engine; raise an actionable error when it is missing."""
    configure_tesseract()
    import pyocr

    tools = pyocr.get_available_tools()
    if not tools:
        raise RuntimeError(
            "Tesseract OCR was not found. Install Tesseract on this PC and "
            "make sure tesseract.exe is available, or run the bundled Windows EXE."
        )
    # Explicitly prefer the executable wrapper over any native libtesseract
    # binding, making deployment more predictable on Windows.
    return next(
        (tool for tool in tools if tool.get_name().lower() == "tesseract"),
        tools[0],
    )


def available_languages(tool) -> list[str]:
    languages = tool.get_available_languages() or []
    return sorted(set(languages), key=lambda lang: (lang != "eng", lang))


def extract_text(image_path: str | Path, language: str = "eng", tool=None) -> str:
    """Return text extracted from the selected image using PyOCR."""
    import pyocr.builders

    engine = tool if tool is not None else get_ocr_engine()
    with Image.open(image_path) as source:
        # Honor the rotation metadata found in many camera photos.
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.load()

    result = engine.image_to_string(
        image,
        lang=language,
        builder=pyocr.builders.TextBuilder(),
    )
    return result.strip().replace("\x0c", "")
