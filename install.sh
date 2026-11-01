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
echo "[2/4] Dependencies installed in .venv"
if ! command -v gmgn-cli >/dev/null 2>&1; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "Node.js 18+ is required for gmgn-cli. Install it (macOS: brew install node · Ubuntu: see https://nodejs.org) and run again."
    exit 1
  fi
  echo "Installing gmgn-cli..."
  npm install -g gmgn-cli || { echo "npm install failed. Try: sudo npm install -g gmgn-cli"; exit 1; }
fi
echo "[3/4] gmgn-cli ready"
if grep -qE '^GMGN_API_KEY=.+' "$HOME/.config/gmgn/.env" 2>/dev/null; then
  echo "[4/4] GMGN API key found"
else
  echo "[4/4] Connect your GMGN API key (get one at https://gmgn.ai/ai)"
  .venv/bin/python -m kraken setup
fi
chmod +x run.sh 2>/dev/null || true
echo; echo "Done! Start kraken with:  ./run.sh"
echo "Change keys later with:   .venv/bin/python -m kraken setup"; echo
