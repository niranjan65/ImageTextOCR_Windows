import tempfile
from pathlib import Path
import unittest
from PIL import Image, ImageDraw, ImageFont
import ocr_core


class OCRDocumentTests(unittest.TestCase):
    def test_positioned_words_include_confidence_and_bounds(self):
        self.assertTrue(hasattr(ocr_core, "extract_document"), "Positioned OCR API is missing")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "text.png"
            image = Image.new("RGB", (700, 180), "white")
            ImageDraw.Draw(image).text((30, 50), "Form ID: 0430", font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 40), fill="black")
            image.save(path)
            result = ocr_core.extract_document(path)
            self.assertIn("0430", [w.content for w in result.words])
            for word in result.words:
                x1, y1, x2, y2 = word.bbox
                self.assertTrue(0 <= x1 < x2 <= result.width)
                self.assertTrue(0 <= y1 < y2 <= result.height)
                self.assertTrue(0 <= word.confidence <= 100)

    def test_original_text_extraction_remains_compatible(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "text.png"
            image = Image.new("RGB", (700, 180), "white")
            ImageDraw.Draw(image).text((30, 50), "CAPTURE 12345", font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 40), fill="black")
            image.save(path)
            self.assertIn("CAPTURE 12345", ocr_core.extract_text(path))

    def test_rotated_input_uses_displayed_orientation(self):
        self.assertTrue(hasattr(ocr_core, "extract_document"), "Positioned OCR API is missing")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rotated.jpg"
            image = Image.new("RGB", (600, 180), "white")
            ImageDraw.Draw(image).text((25, 50), "ORIENT 0430", font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 40), fill="black")
            rotated = image.transpose(Image.Transpose.ROTATE_90)
            exif = rotated.getexif()
            exif[274] = 6
            rotated.save(path, exif=exif)
            result = ocr_core.extract_document(path)
            self.assertGreater(result.width, result.height)
            self.assertIn("0430", result.text)
