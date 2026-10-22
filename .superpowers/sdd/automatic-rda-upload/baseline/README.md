# ImageTextOCR — standalone Windows OCR app

A local desktop program to **select an image, recognize text with PyOCR + Tesseract, and copy or save the results**. It uses Tkinter and Pillow, and processes the image on the PC without uploading it to a server.

## Build a Windows `.exe` in a few steps

> **Important:** This folder contains source code and a Windows build script, **not a precompiled `.exe`**. To produce a Windows `.exe`, perform the build on a Windows PC. PyInstaller cannot directly cross-compile a Windows exe from Linux.

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

To run the capture integration tests (requires an interactive Windows desktop):

```bat
.venv\Scripts\python.exe -m unittest discover -v
```

The tests use generated screen images and include a real desktop capture of a temporary calibration window. The OCR integration test also requires Tesseract and its English model.

## Troubleshooting

- **OCR engine not found:** Run `build_windows.bat` with Tesseract installed on the build PC. For `.py` execution, install Tesseract and make `tesseract.exe` discoverable.
- **English OCR model missing:** Ensure `C:\Program Files\Tesseract-OCR\tessdata\eng.traineddata` exists and rebuild.
- **Other languages:** Install the appropriate `.traineddata` files into Tesseract's `tessdata` folder *before* running the build script. Then choose the language in the app.
- **Windows security dialog:** Unsigned user-built executables may be subject to SmartScreen checks. Sign distributed builds if this will be delivered to customers.
- **Unexpected DLL or language errors:** Make sure the source app works on the Windows build machine; Tesseract installations vary. Verify the bundled OCR exe on a second Windows machine before distributing it.

## License note

PyOCR is licensed under GPLv3+ and Tesseract under Apache 2.0. Check applicable license compliance, including source availability and license notices, before distributing a packaged executable to other people. See the upstream project repositories for details.
