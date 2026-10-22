"""Open the preserved capture for user review; never automatically submit it."""
from pathlib import Path
import sys

workspace = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(workspace))
from ocr_app import OCRApp

app = OCRApp()
app._select_image(workspace / 'tests_support/fixtures/reported_rda_capture.png')
app.after(250, app._review_and_send)
app.mainloop()
