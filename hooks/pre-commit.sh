#!/usr/bin/env bash
# Auto-increment the patch version in pyproject.toml if it wasn't changed manually.
set -euo pipefail

PYPROJECT="pyproject.toml"

if ! [ -f "$PYPROJECT" ]; then
    exit 0
fi

if git diff --cached --quiet -- "$PYPROJECT" 2>/dev/null; then
    version_changed=false
else
    if git diff --cached -- "$PYPROJECT" | grep -q '^[+-]version'; then
        version_changed=true
    else
        version_changed=false
    fi
fi

if [ "$version_changed" = true ]; then
    exit 0
fi

current="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$PYPROJECT")"
if [ -z "$current" ]; then
    exit 0
fi

IFS='.' read -r major minor patch <<< "$current"
patch=$((patch + 1))
new_version="${major}.${minor}.${patch}"

sed -i "s/^version = \"${current}\"/version = \"${new_version}\"/" "$PYPROJECT"
git add "$PYPROJECT"
echo "Auto-bumped version: ${current} -> ${new_version}"
