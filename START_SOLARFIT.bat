@echo off
setlocal
cd /d "%~dp0"
title SolarFit - Local Rooftop Analysis
if not exist ".venv\solarfit-ready" goto setup
if not exist ".venv\solarfit-map-ready" goto setup
if not exist "frontend\dist\index.html" goto setup
goto run
:setup
echo Setting up SolarFit. First run downloads Python packages and CUDA support.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
if errorlevel 1 goto error
:run
".venv\Scripts\python.exe" scripts\launch.py %*
if errorlevel 1 goto error
exit /b 0
:error
echo.
echo SolarFit could not start. Read the error above.
pause
exit /b 1
