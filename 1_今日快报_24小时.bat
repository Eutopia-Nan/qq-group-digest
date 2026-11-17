@echo off
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo [ERROR] Python not found. Install it from https://www.python.org and tick "Add python.exe to PATH".
  pause
  exit /b 1
)
%PY% digest.py --preset daily
pause
