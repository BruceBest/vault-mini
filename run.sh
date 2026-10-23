#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
PYTHON="${VAULT_MINI_PYTHON:-$PWD/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  printf 'Missing Python environment: %s\nRun: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt\n' "$PYTHON" >&2
  exit 1
fi
exec "$PYTHON" server.py "$@"
