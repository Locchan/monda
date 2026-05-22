#!/usr/bin/env bash
# Set patch to <commit_count><branch_initial>, e.g. 1.1.29m
set -euo pipefail

PYPROJECT="pyproject.toml"

if ! [ -f "$PYPROJECT" ]; then
    exit 0
fi

current="$(sed -n 's/^version = "\([^"]*\)"/\1/p' "$PYPROJECT")"
if [ -z "$current" ]; then
    exit 0
fi

IFS='.' read -r major minor _ <<< "$current"

branch="$(git rev-parse --abbrev-ref HEAD)"
branch_letter="${branch:0:1}"
commit_count=$(( $(git rev-list --count HEAD 2>/dev/null || echo 0) + 1 ))

new_version="${major}.${minor}.${commit_count}${branch_letter}"

if [ "$current" = "$new_version" ]; then
    exit 0
fi

sed -i "s/^version = \"${current}\"/version = \"${new_version}\"/" "$PYPROJECT"
git add "$PYPROJECT"
echo "Auto-set version: ${current} -> ${new_version}"
