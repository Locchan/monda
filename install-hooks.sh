#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOKS_SRC="$SCRIPT_DIR/hooks"
HOOKS_DST="$SCRIPT_DIR/.git/hooks"

if [ ! -d "$HOOKS_DST" ]; then
    echo "ERROR: not a git repository (no .git/hooks directory)." >&2
    exit 1
fi

for hook in "$HOOKS_SRC"/*.sh; do
    [ -f "$hook" ] || continue
    name="$(basename "$hook" .sh)"
    dst="$HOOKS_DST/$name"
    cp "$hook" "$dst"
    chmod +x "$dst"
    echo "Installed hook: $name"
done
