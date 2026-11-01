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
echo "[1/3] Python OK ($PY)"
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --quiet
.venv/bin/python -m pip install -r requirements.txt --quiet
echo "[2/3] Dependencies installed in .venv"
if command -v gmgn-cli >/dev/null 2>&1; then
  echo "[3/3] gmgn-cli found"
elif command -v npm >/dev/null 2>&1; then
  read -r -p "[3/3] Install gmgn-cli for live GMGN data? (needed only with an API key) [y/N] " a || a=""
  case "$a" in [yY]*) npm install -g gmgn-cli ;; esac
else
  echo "[3/3] Skipped gmgn-cli (Node.js not installed). kraken runs on demo data without it."
fi
chmod +x run.sh 2>/dev/null || true
echo; echo "Done! Start kraken with:  ./run.sh"
echo "Optional - connect your GMGN key:  .venv/bin/python -m kraken setup"; echo
