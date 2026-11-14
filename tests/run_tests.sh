#!/usr/bin/env bash
# Create an isolated venv, install monda editable + test deps, run pytest.
set -euo pipefail

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$TEST_DIR/.." && pwd)"
VENV="${TEST_VENV:-$TEST_DIR/.venv}"

python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

python -m pip install -U pip setuptools wheel >/dev/null
python -m pip install -e "$ROOT" -r "$TEST_DIR/requirements.txt"

cd "$TEST_DIR"
exec python -m pytest "$@"
