@echo off
setlocal enableextensions

rem ----------------------------------------------------------------------
rem AriasSTT bundle script.
rem
rem Produces a self-contained folder install at dist\AriasSTT\ that does
rem NOT require Python on the target machine. The Whisper model is still
rem fetched from HuggingFace at first run and cached under
rem %USERPROFILE%\.cache\huggingface, so the bundle stays under ~700 MB.
rem
rem Run:  build.bat
rem Output: dist\AriasSTT\AriasSTT.exe
rem ----------------------------------------------------------------------

set "ROOT=%~dp0"
set "VENV=%ROOT%venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo [build] venv not found at %VENV%. Run setup.bat first.
    exit /b 1
)

echo [build] Cleaning previous output...
if exist "%ROOT%build" rmdir /s /q "%ROOT%build"
if exist "%ROOT%dist"  rmdir /s /q "%ROOT%dist"

echo [build] Bundling AriasSTT (folder mode, no console window)...
"%PY%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --name AriasSTT ^
    --windowed ^
    --collect-all faster_whisper ^
    --collect-all ctranslate2 ^
    --collect-all sounddevice ^
    --collect-all pynput ^
    --collect-all pystray ^
    --collect-all plyer ^
    --collect-all pyperclip ^
    --collect-all PIL ^
    --copy-metadata faster_whisper ^
    --copy-metadata ctranslate2 ^
    --hidden-import plyer.platforms.win.notification ^
    --hidden-import pynput.keyboard._win32 ^
    --hidden-import pynput.mouse._win32 ^
    --hidden-import pystray._win32 ^
    "%ROOT%dictate.py"

if errorlevel 1 (
    echo [build] Bundle failed.
    exit /b 1
)

echo.
echo [build] Done. Bundle at: dist\AriasSTT\
echo [build] Smoke test:        dist\AriasSTT\AriasSTT.exe
echo.
echo Next: run installer.bat to compile the Inno Setup installer.
endlocal
