#!/usr/bin/env bash
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "kraken is not installed yet. Run ./install.sh first."; exit 1; }
exec .venv/bin/python -m kraken "$@"
