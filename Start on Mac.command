#!/bin/bash
# Double-click to run AutoClip Studio. First launch installs everything (a few minutes).
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null; then
  echo "Python 3.10 or newer is required. Install it from https://www.python.org/downloads/ and try again."
  read -r -p "Press Enter to close"; exit 1
fi
[ -d .venv ] || python3 -m venv .venv || { read -r -p "Could not create environment. Press Enter"; exit 1; }
source .venv/bin/activate
if ! cmp -s requirements.txt .venv/.installed; then
  echo "Installing AutoClip Studio (first launch only)..."
  python -m pip install --upgrade pip >/dev/null
  pip install -r requirements.txt && cp requirements.txt .venv/.installed || { read -r -p "Install failed. Press Enter"; exit 1; }
fi
python app.py
