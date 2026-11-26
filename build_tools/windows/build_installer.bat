@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows_installer.ps1" %*
set "buildExitCode=%ERRORLEVEL%"
if not "%buildExitCode%"=="0" (
    echo Build installer fallita. Leggi l'errore riportato sopra.
    pause
)
exit /b %buildExitCode%
