@echo off
call "%~dp0START_SOLARFIT.bat" --ngrok %*
exit /b %errorlevel%
