@echo off
rem Tiny PATH shim. Talks to the one UEFN Ducky window; does not load the app.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0ducky.ps1" %*
exit /b %ERRORLEVEL%
