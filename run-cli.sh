#!/usr/bin/env bash
# Run the EVE LP -> ISK optimizer command-line tool on macOS / Linux.
# Arguments are passed straight through, e.g.:
#   ./run-cli.sh --corp "Caldari Navy:169675" --top 30
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment (first run)..."
  "$PY" -m venv .venv
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
fi

exec .venv/bin/python -m eve_lp "$@"
