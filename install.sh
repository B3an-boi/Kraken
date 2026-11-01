#!/usr/bin/env bash
# kraken installer for macOS / Linux. Run from the repo folder:  ./install.sh
set -euo pipefail
cd "$(dirname "$0")"
echo; echo "  kraken installer"; echo
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10+ not found. Install it (macOS: brew install python · Ubuntu: sudo apt install python3 python3-venv) and run again."
  exit 1
fi
echo "[1/4] Python OK ($PY)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet
echo "[2/4] Python packages installed"

if ! command -v gmgn-cli >/dev/null 2>&1; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "Node.js 18+ is required for gmgn-cli. Install it (macOS: brew install node · Ubuntu: see https://nodejs.org) and run again."
    exit 1
  fi
  echo "Installing gmgn-cli..."
  npm install -g gmgn-cli || { echo "npm install failed. Try: sudo npm install -g gmgn-cli"; exit 1; }
fi
v=$(gmgn-cli --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
if [ -n "$v" ] && [ "$(printf '%s\n1.7.0\n' "$v" | sort -V | head -1)" != "1.7.0" ]; then
  echo "Updating gmgn-cli ($v -> latest)..."
  npm install -g gmgn-cli@latest || echo "Couldn't update gmgn-cli automatically. Run: npm install -g gmgn-cli@latest"
fi
echo "[3/4] gmgn-cli ready"
chmod +x run.sh 2>/dev/null || true
echo "[4/4] kraken installed"
echo; echo "All set! Starting kraken. Your browser opens to a setup page that connects your GMGN key."
echo "Next time, start it with:  ./run.sh"; echo
exec .venv/bin/python -m kraken
