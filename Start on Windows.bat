@echo off
rem Double-click to run AutoClip Studio. First launch installs everything (a few minutes).
cd /d "%~dp0"
set PY=python
where py >nul 2>nul && set PY=py -3
if not exist .venv (
  %PY% -m venv .venv || (
    echo Python 3.10 or newer is required. Install it from https://www.python.org/downloads/
    echo IMPORTANT: tick "Add python.exe to PATH" during install.
    pause & exit /b 1
  )
)
call .venv\Scripts\activate.bat
fc /b requirements.txt .venv\.installed >nul 2>nul || (
  echo Installing AutoClip Studio ^(first launch only^)...
  python -m pip install --upgrade pip >nul
  pip install -r requirements.txt || (echo Install failed. & pause & exit /b 1)
  copy /y requirements.txt .venv\.installed >nul
)
python app.py
pause
