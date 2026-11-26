@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_linux_installer_wsl.ps1" %*
exit /b %ERRORLEVEL%
