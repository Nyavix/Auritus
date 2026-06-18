@echo off
setlocal enableextensions

REM ----------------------------------------------------------------------
REM Auritus setup
REM   - Creates a local virtual environment in .\venv
REM   - Installs runtime dependencies
REM   - Pre-downloads the faster-whisper medium.en model
REM   - Smoke-tests the install
REM ----------------------------------------------------------------------

cd /d "%~dp0"

echo.
echo === Auritus setup ===
echo Working directory: %CD%
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not on PATH. Install Python 3.10+ and re-run.
    exit /b 1
)

if not exist "venv\Scripts\python.exe" (
    echo [1/5] Creating virtual environment in .\venv ...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        exit /b 1
    )
) else (
    echo [1/5] Virtual environment already exists, reusing.
)

echo.
echo [2/5] Upgrading pip ...
"venv\Scripts\python.exe" -m pip install --upgrade pip wheel setuptools
if errorlevel 1 goto :pip_fail

echo.
echo [3/5] Installing dependencies ...
"venv\Scripts\python.exe" -m pip install ^
    faster-whisper ^
    pynput ^
    pyperclip ^
    sounddevice ^
    numpy ^
    scipy ^
    pystray ^
    Pillow ^
    plyer
if errorlevel 1 goto :pip_fail

echo.
echo [4/5] Downloading faster-whisper medium.en model (first run only, ~1.5 GB) ...
"venv\Scripts\python.exe" -c "from faster_whisper import WhisperModel; WhisperModel('medium.en', device='cpu', compute_type='int8'); print('Model ready.')"
if errorlevel 1 (
    echo [ERROR] Model download failed. Check your internet connection and try again.
    exit /b 1
)

echo.
echo [5/5] Smoke test ...
"venv\Scripts\python.exe" -c "import faster_whisper, pynput, pyperclip, sounddevice, numpy, scipy, pystray, PIL, plyer; print('All imports OK.')"
if errorlevel 1 (
    echo [ERROR] Smoke test failed.
    exit /b 1
)

echo.
echo [6/6] Checking for whisper.cpp GPU binary ...
if not exist "vendor\whisper-cpp\whisper-server.exe" (
    echo [NOTICE] vendor\whisper-cpp\whisper-server.exe not found.
    echo          GPU backend will be unavailable until a CI release build
    echo          adds the binary. CPU backend works without it.
) else (
    echo         whisper-server.exe present - GPU backend available.
)

echo.
echo === Setup complete ===
echo.
echo Run the app:        pythonw dictate.py    (no console window)
echo Run with console:   python  dictate.py    (handy for debugging)
echo Auto-start on login: install_startup.bat
echo.
exit /b 0

:pip_fail
echo [ERROR] pip install failed.
exit /b 1
