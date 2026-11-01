@echo off
title kraken
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo kraken is not installed yet. Double-click install.cmd first.
  pause
  exit /b 1
)
echo Starting kraken... keep this window open while you use it. Close it to stop kraken.
".venv\Scripts\python.exe" -m kraken %*
if errorlevel 1 pause
