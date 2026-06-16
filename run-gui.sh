#!/usr/bin/env bash
# Launch the EVE LP -> ISK optimizer GUI on macOS / Linux.
# On first run it creates a local virtual environment and installs deps.
#
# Requires Tkinter for the GUI:
#   Debian/Ubuntu : sudo apt install python3-tk
#   Fedora        : sudo dnf install python3-tkinter
#   Arch          : sudo pacman -S tk
#   macOS (brew)  : brew install python-tk
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment (first run)..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python -m eve_lp.gui "$@"
