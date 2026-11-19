@echo off
setlocal
cd /d "%~dp0" || exit /b 1
where py >nul 2>nul && py -3 -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul && goto :use_py
where python >nul 2>nul && python -c "import sys; sys.exit(sys.version_info < (3, 8))" >nul 2>nul && goto :use_python
echo [ERROR] Python 3.8+ was not found. Install it from https://www.python.org and add it to PATH.
pause
exit /b 1

:use_py
set "PY=py -3"
goto :run
:use_python
set "PY=python"
:run
echo Starting the QQ group digest interface. Keep this window open while you use it; close it to quit.
%PY% app.py %*
set "RESULT=%ERRORLEVEL%"
pause
exit /b %RESULT%
