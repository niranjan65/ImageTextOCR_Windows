# ImageTextOCR — standalone Windows OCR app

A Windows desktop program to **capture an RDA screen, recognize text locally, and automatically create a new RDA Information record in Skylink**. It also supports ordinary image-to-text extraction, copy and text export. Screenshots remain local; only mapped field values are sent to the configured site.

## Build a Windows `.exe` in a few steps

The current Windows build is at `dist\ImageTextOCR.exe`. To rebuild it, follow these steps on Windows. PyInstaller cannot directly cross-compile a Windows exe from Linux.

1. Install **Python 3.11 or 3.12** on Windows, including `py` / `python` launcher on PATH.
2. Install **Tesseract OCR for Windows** using the [UB Mannheim Windows installer](https://github.com/UB-Mannheim/tesseract/wiki). Use the default install path `C:\Program Files\Tesseract-OCR` and select **English language data** (and other languages if you need them).
3. Extract this project to a directory (e.g. `C:\OCR\ImageTextOCR_Windows`).
4. Double-click `build_windows.bat`. It creates a Python virtual environment, installs the dependencies, and builds a single-file executable containing Tesseract.
5. Your program will appear at **`dist\ImageTextOCR.exe`**. Double-click it and choose an image.

The resulting `.exe` includes Python, PyOCR, Pillow, the Tesseract engine, Tesseract DLLs, and the language models installed in your build PC's Tesseract `tessdata` folder. People running it should **not need to install Python or Tesseract**.

If Tesseract is installed in a custom folder, open a Command Prompt in this folder and run:

```bat
set "TESSERACT_HOME=D:\Tools\Tesseract-OCR"
build_windows.bat
```

## Run without creating an `.exe`

```bat
py -3 -m pip install pyocr==0.8.5 Pillow
py -3 ocr_app.py
```

This source-code method requires a separately installed Tesseract OCR executable. Running `tesseract --version` in Command Prompt is a useful basic installation check; the app also looks at the default Windows install locations.

## How to use

1. Click **Browse image...** and select `.jpg`, `.jpeg`, `.png`, `.bmp`, `.gif`, `.tif`, `.tiff`, or `.webp`. Alternatively, click **Capture Screenshot**, then drag across the screen and release to capture an area. The app hides while you select; press **Esc** or right-click to cancel.
2. Select an OCR language installed with Tesseract (default: `eng` = English).
3. Click **Extract Text**.
4. Edit the extracted text if necessary, then **Copy Text** or **Save .txt**.

Only the first image/frame of multi-frame TIFF/GIF files is processed. Quality is best with clear, straight, high-resolution scans; OCR may make mistakes with handwriting, tables, faint scans, or unusual layouts.

Captured regions appear in the image preview and use the same **Extract Text** action. Captures are stored temporarily on this PC and removed when the app closes normally.

## Automatically send captured RDA values to Skylink

1. Open **Connection Settings**. The default site is `https://skylink.dev.advtinni.com`.
2. Enter your ERPNext user's **API Key** and **API Secret**, then click **Test Connection & Apply**. Both entries are masked and kept only in memory. The API user must have create/read access to RDA Information and read access to its DocType schema and referenced Link values. Credentials are never saved in source or preferences.
3. Leave **Auto-send captures** enabled. Capture the RDA area with section headings, column headings, field labels and their values. OCR starts automatically, then recognized values are mapped to the actual DocType fieldnames.
4. Every configured capture sends its mapped values immediately, including low-confidence OCR values, and creates **one new record**. There is no mandatory review, warning checkbox or confirmation prompt. The app fetches the created record again to verify submitted fields. **Open Saved Record** opens that document. Every new capture/intentional send creates another record, even if the Revenue Item ID already exists.
5. **Review & Send RDA** is optional. It lets you edit values with **Apply**, omit fields, or export JSON. **Send New Record** sends directly without requiring acknowledgment of OCR warnings. Unseen fields remain omitted because no captured value exists for them.

Capture cancellation and browsing a file never silently send data. Manual **Extract Text** does not re-send an already submitted capture. Disable Auto-send if you prefer to review before each send. Ordinary text editing does not edit the mapped JSON; use the review dialog for field corrections.

If the save response is lost, the app reports an **unknown save outcome** and does not retry automatically. Check the site before another explicit send; the record may already exist. A verification failure retains the saved-record link; **Save Details** shows each mismatched field's expected and stored values. Check this record before creating a replacement.

The local mapper targets the RDA interface supplied with this project. It sends whatever it can map to the known DocType fields. Confidence and layout diagnostics do not block sending or appear as UI warnings. Invalid-looking dates/numbers are sent as captured when normalization fails; ERPNext enforces its own field types, required fields, permissions and Link rules. Actual API failures and saved-field mismatches remain visible. Synthetic OCR tests and API field verification are separate checks; neither guarantees every screenshot will be read without OCR errors.

Wrapped summary headings are read within the visible table borders so they stay separate from values. Small captures are enlarged before OCR. The regression suite includes a real captured RDA screen and checks all 48 unambiguous populated values against its reference. Its ambiguous Pickup Type is sent exactly as read, and the full 49-field payload is tested without a review gate.

Only the site URL and Auto-send preference are saved under `%LOCALAPPDATA%\ImageTextOCR\preferences.json`. Optional `SKYLINK_API_KEY` and `SKYLINK_API_SECRET` process environment variables can bootstrap an API connection at launch; both are consumed into memory. `SKYLINK_SITE_URL` optionally selects its site. Token authentication uses the standard `Authorization: token api_key:api_secret` header and does not require a browser session or Desk CSRF token. Legacy `SKYLINK_SESSION_ID` bootstrap remains supported when no API credentials are supplied; incomplete API credentials fail without falling back to a session.

See the official [Frappe token authentication documentation](https://docs.frappe.io/framework/user/en/guides/integration/rest_api/token_based_authentication) for API credential setup.

To run the capture integration tests (requires an interactive Windows desktop):

```bat
.venv\Scripts\python.exe -m unittest discover -v
```

The tests use generated screen images and include a real desktop capture of a temporary calibration window. The OCR integration test also requires Tesseract and its English model.

The normal test suite uses a controlled HTTP fixture and **does not create records on Skylink**. An explicit live test is available:

```bat
.venv\Scripts\python.exe verify_rda_live.py --image "C:\path\to\rda.png" --create-count 2
```

This prompts for the API key and secret without displaying them (or consumes `SKYLINK_API_KEY` and `SKYLINK_API_SECRET`). It deliberately creates two records and writes a credential-free `rda_upload_live_report.json` with their links and saved-field comparisons. Use `--synthetic-fixture` when the image is generated test data. Mapping diagnostics remain in the local report and do not prevent sending. It never updates or automatically deletes existing records. Legacy `SKYLINK_SESSION_ID` remains usable when no API credentials are supplied.

## Troubleshooting

- **OCR engine not found:** Run `build_windows.bat` with Tesseract installed on the build PC. For `.py` execution, install Tesseract and make `tesseract.exe` discoverable.
- **English OCR model missing:** Ensure `C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata` exists and rebuild.
- **Other languages:** Install the appropriate `.traineddata` files into Tesseract's `tessdata` folder *before* running the build script. Then choose the language in the app.
- **Windows security dialog:** Unsigned user-built executables may be subject to SmartScreen checks. Sign distributed builds if this will be delivered to customers.
- **Unexpected DLL or language errors:** Make sure the source app works on the Windows build machine; Tesseract installations vary. Verify the bundled OCR exe on a second Windows machine before distributing it.

## License note

PyOCR is licensed under GPLv3+ and Tesseract under Apache 2.0. Check applicable license compliance, including source availability and license notices, before distributing a packaged executable to other people. See the upstream project repositories for details.
