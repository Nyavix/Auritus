@echo off
setlocal enableextensions

rem ----------------------------------------------------------------------
rem AriasSTT installer compiler.
rem
rem Requires Inno Setup 6 (compiler iscc.exe). Install with:
rem   winget install JRSoftware.InnoSetup
rem
rem Output: installer-output\AriasSTT-Setup-vX.Y.Z.exe
rem ----------------------------------------------------------------------

set "ROOT=%~dp0"

rem Common Inno Setup install paths.
set "ISCC1=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
set "ISCC2=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if exist "%ISCC1%" (
    set "ISCC=%ISCC1%"
) else if exist "%ISCC2%" (
    set "ISCC=%ISCC2%"
) else (
    where iscc >nul 2>&1
    if errorlevel 1 (
        echo [installer] Inno Setup not found.
        echo            Install with: winget install JRSoftware.InnoSetup
        exit /b 1
    )
    set "ISCC=iscc.exe"
)

if not exist "%ROOT%dist\AriasSTT\AriasSTT.exe" (
    echo [installer] Bundle not found. Run build.bat first.
    exit /b 1
)

echo [installer] Compiling installer with %ISCC% ...
"%ISCC%" "%ROOT%installer.iss"
if errorlevel 1 (
    echo [installer] Inno compile failed.
    exit /b 1
)

echo.
echo [installer] Done. Output in installer-output\
endlocal
