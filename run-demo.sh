#!/usr/bin/env bash
# Try the product on a simulated network (Mac and Linux). Needs Python 3.11+ and Git.
#   ./run-demo.sh            start (or carry on where you left off)
#   ./run-demo.sh --reset    start again from a fresh demo network
# Then open http://127.0.0.1:8710 and sign in as demo / demo-password. Ctrl+C stops it.
set -euo pipefail
cd "$(dirname "$0")/backend"
PY="$(command -v python3 || command -v python)" || { echo "Install Python 3.11 or newer first." >&2; exit 1; }
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11 or newer is needed (found $("$PY" --version))." >&2; exit 1; }
command -v git >/dev/null || { echo "Install Git first (config backups are kept in a git repository)." >&2; exit 1; }
if [[ ! -x .venv/bin/python ]]; then
  echo "First run: setting up (a minute or two)..."
  "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q --disable-pip-version-check -r requirements-dev.txt
exec .venv/bin/python -m app.demo "$@"
