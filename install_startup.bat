@echo off
setlocal enableextensions

REM ----------------------------------------------------------------------
REM Creates a shortcut in the Windows Startup folder so Auritus launches
REM on every login, using pythonw.exe so no console window appears.
REM
REM Why startup folder over Task Scheduler:
REM   - Task Scheduler GUI apps run in Session 0 by default unless you
REM     carefully configure "Run only when user is logged on", and even then
REM     tray icons can be flaky. Startup folder runs in the user's normal
REM     interactive session, which is what a tray app needs.
REM ----------------------------------------------------------------------

cd /d "%~dp0"

set "SCRIPT=%CD%\dictate.py"
set "PYW=%CD%\venv\Scripts\pythonw.exe"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "LNK=%STARTUP%\Auritus.lnk"

if not exist "%PYW%" (
    echo [ERROR] %PYW% not found. Run setup.bat first.
    exit /b 1
)

if not exist "%SCRIPT%" (
    echo [ERROR] %SCRIPT% not found.
    exit /b 1
)

if not exist "%STARTUP%" (
    echo [ERROR] Startup folder not found: %STARTUP%
    exit /b 1
)

echo Creating shortcut: %LNK%
echo Target:            %PYW%
echo Args:              "%SCRIPT%"
echo WorkingDir:        %CD%

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell;" ^
    "$s = $ws.CreateShortcut('%LNK%');" ^
    "$s.TargetPath = '%PYW%';" ^
    "$s.Arguments = '\"%SCRIPT%\"';" ^
    "$s.WorkingDirectory = '%CD%';" ^
    "$s.WindowStyle = 7;" ^
    "$s.Description = 'Auritus push-to-talk Whisper dictation';" ^
    "$s.Save()"

if errorlevel 1 (
    echo [ERROR] Failed to create shortcut.
    exit /b 1
)

echo.
echo Done. Auritus will launch automatically on next login.
echo To remove: run uninstall_startup.bat
exit /b 0
