@echo off
setlocal enableextensions

set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Auritus.lnk"

if exist "%LNK%" (
    del "%LNK%"
    echo Removed startup shortcut.
) else (
    echo No startup shortcut found at %LNK%.
)
exit /b 0
