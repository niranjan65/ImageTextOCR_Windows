"""OCR engine adapter for ImageTextOCR, powered by PyOCR + Tesseract."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
import sys

from PIL import Image, ImageOps


@dataclass(frozen=True)
class OCRWord:
    content: str
    bbox: tuple[int, int, int, int]
    confidence: float


@dataclass(frozen=True)
class OCRTableCell:
    header: tuple[OCRWord, ...]
    values: tuple[OCRWord, ...]


@dataclass(frozen=True)
class OCRTable:
    cells: tuple[OCRTableCell, ...]
    bbox: tuple[int, int, int, int]


@dataclass(frozen=True)
class OCRDocument:
    text: str
    words: tuple[OCRWord, ...]
    width: int
    height: int
    tables: tuple[OCRTable, ...] = ()


def word_lines(words):
    """Group words by their vertical centers, keeping columns in left-to-right order."""
    lines = []
    for word in sorted(words, key=lambda w: (w.bbox[1], w.bbox[0])):
        center = (word.bbox[1] + word.bbox[3]) / 2
        height = word.bbox[3] - word.bbox[1]
        target = next((line for line in reversed(lines)
                       if abs(center - sum((w.bbox[1] + w.bbox[3]) / 2 for w in line) / len(line))
                       < max(4, height * 0.55)), None)
        if target is None:
            lines.append([word])
        else:
            target.append(word)
    return [sorted(line, key=lambda w: w.bbox[0]) for line in lines]


def extract_document(image_path: str | Path, language: str = "eng", tool=None) -> OCRDocument:
    """Read local OCR words, coordinates and confidence for section-aware mapping."""
    import pyocr.builders

    engine = tool if tool is not None else get_ocr_engine()
    from ocr_tables import detect_header_grid, read_header_grid
    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    try:
        grid = detect_header_grid(image)
        scale = 4 if image.width < 1200 else 2 if image.width < 1800 else 1
        original = image.copy() if grid else None
        if scale > 1:
            enlarged = image.resize((image.width * scale, image.height * scale), Image.Resampling.LANCZOS)
            image.close()
            image = enlarged
        boxes = engine.image_to_string(image, lang=language, builder=pyocr.builders.WordBoxBuilder(tesseract_layout=11))
        words = tuple(OCRWord(box.content, (*box.position[0], *box.position[1]),
                              max(0.0, min(100.0, float(box.confidence))))
                      for box in boxes if box.content.strip())
        text = "\n".join(" ".join(w.content for w in line) for line in word_lines(words))
        tables = ()
        if original is not None:
            try:
                tables = (read_header_grid(original, grid, engine, language, scale, words),)
            finally:
                original.close()
        return OCRDocument(text, words, image.width, image.height, tables)
    finally:
        image.close()


def configure_tesseract() -> None:
    """Make the bundled Windows Tesseract engine discoverable by PyOCR.

    `build_windows.bat` embeds tesseract.exe, its DLLs, and tessdata in the
    `tesseract` subdirectory of the PyInstaller extraction folder.
    """
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled = bundle_root / "tesseract"
    if (bundled / "tesseract.exe").is_file():
        os.environ["PATH"] = str(bundled) + os.pathsep + os.environ.get("PATH", "")
        # Tesseract resolves eng.traineddata directly inside TESSDATA_PREFIX.
        os.environ["TESSDATA_PREFIX"] = str(bundled / "tessdata")
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
