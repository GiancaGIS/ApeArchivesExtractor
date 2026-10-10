@echo off
setlocal
if "%~1"=="" (
	powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows_installer.ps1" -DevelopmentBuild
) else (
	powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build_windows_installer.ps1" %*
)
set "buildExitCode=%ERRORLEVEL%"
if not "%buildExitCode%"=="0" (
    echo.
    echo Build installer fallita. Leggi l'errore riportato sopra.
    pause
)
exit /b %buildExitCode%
