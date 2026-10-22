@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Build ImageTextOCR for Windows

echo ============================================================
echo  ImageTextOCR - Build Windows standalone executable
 echo ============================================================
echo.

where py >nul 2>&1
if %errorlevel%==0 (
    set "BOOTSTRAP=py -3"
) else (
    set "BOOTSTRAP=python"
)

%BOOTSTRAP% --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3 was not found. Install Python 3.11 or 3.12 first.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating isolated Python environment...
    %BOOTSTRAP% -m venv .venv
    if errorlevel 1 goto failed
)
set "PYTHON=%CD%\.venv\Scripts\python.exe"

echo Installing Python dependencies...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto failed

if not defined TESSERACT_HOME (
    if exist "%ProgramFiles%\Tesseract-OCR\tesseract.exe" (
        set "TESSERACT_HOME=%ProgramFiles%\Tesseract-OCR"
    ) else if exist "%ProgramFiles(x86)%\Tesseract-OCR\tesseract.exe" (
        set "TESSERACT_HOME=%ProgramFiles(x86)%\Tesseract-OCR"
    )
)

if not defined TESSERACT_HOME (
    echo.
    echo ERROR: Tesseract not found.
    echo Install it from https://github.com/UB-Mannheim/tesseract/wiki
    echo or set the TESSERACT_HOME environment variable to its install folder.
    pause
    exit /b 1
)
if not exist "%TESSERACT_HOME%\tesseract.exe" (
    echo ERROR: Missing "%TESSERACT_HOME%\tesseract.exe"
    pause
    exit /b 1
)
if not exist "%TESSERACT_HOME%\tessdata\eng.traineddata" (
    echo ERROR: English OCR model missing.
    echo During Tesseract installation, install English language data.
    pause
    exit /b 1
)

echo Bundling Tesseract from "%TESSERACT_HOME%"
echo.
"%PYTHON%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --windowed ^
    --name ImageTextOCR ^
    --collect-submodules pyocr ^
    --add-binary "%TESSERACT_HOME%\tesseract.exe;tesseract" ^
    --add-binary "%TESSERACT_HOME%\*.dll;tesseract" ^
    --add-data "%TESSERACT_HOME%\tessdata;tesseract\tessdata" ^
    ocr_app.py
if errorlevel 1 goto failed

echo.
echo ============================================================
echo SUCCESS: dist\ImageTextOCR.exe
echo Copy the executable to another Windows PC to run it.
echo ============================================================
pause
exit /b 0

:failed
echo.
echo BUILD FAILED - See the error output above.
pause
exit /b 1
