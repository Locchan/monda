#!/usr/bin/env bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "This installer must run as root." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR=/opt/monda/venv
CONFIG_DIR=/etc/monda
CONFIG_FILE="$CONFIG_DIR/config.json"
MIN_PYTHON="3.10"

# If this checkout is a git repo and the local branch is behind its upstream,
# offer to pull. If the user pulls, re-exec to pick up the new install.sh.
maybe_self_update() {
    command -v git >/dev/null 2>&1 || return 0
    git -C "$SCRIPT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0

    echo "Checking the git checkout for updates..."
    if ! git -C "$SCRIPT_DIR" fetch --quiet 2>/dev/null; then
        echo "  git fetch failed; continuing with the local checkout."
        return 0
    fi

    local upstream
    upstream="$(git -C "$SCRIPT_DIR" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
    if [ -z "$upstream" ]; then
        echo "  no upstream tracking branch configured; skipping update check."
        return 0
    fi

    local local_head upstream_head
    local_head="$(git -C "$SCRIPT_DIR" rev-parse HEAD)"
    upstream_head="$(git -C "$SCRIPT_DIR" rev-parse "$upstream")"

    if [ "$local_head" = "$upstream_head" ]; then
        echo "  already at $upstream ($local_head)."
        return 0
    fi

    local local_date upstream_date
    local_date="$(git -C "$SCRIPT_DIR" log -1 --format='%ci' HEAD)"
    upstream_date="$(git -C "$SCRIPT_DIR" log -1 --format='%ci' "$upstream")"

    echo "Local checkout is behind $upstream:"
    echo "  local:    $local_head ($local_date)"
    echo "  upstream: $upstream_head ($upstream_date)"
    local answer
    read -rp "Run 'git pull --ff-only' before installing? [y/N]: " answer
    case "$answer" in
        [yY]|[yY][eE][sS])
            git -C "$SCRIPT_DIR" pull --ff-only
            echo "Re-launching installer with the updated code..."
            exec bash "$0" "$@"
            ;;
        *)
            echo "Skipping pull; installing the current local checkout."
            ;;
    esac
}

maybe_self_update "$@"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 is required but was not found on PATH." >&2
    exit 1
fi

PYTHON_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if ! python3 -c "import sys; exit(0 if sys.version_info >= (${MIN_PYTHON//./, }) else 1)"; then
    echo "ERROR: Python >= $MIN_PYTHON is required (found $PYTHON_VER)." >&2
    exit 1
fi
echo "Found Python $PYTHON_VER (>= $MIN_PYTHON required)."

if ! python3 -c "import venv, ensurepip" 2>/dev/null; then
    cat >&2 <<'EOF'
ERROR: python3 -m venv is not fully usable on this system
       (the 'venv' or 'ensurepip' module is missing).

Install the appropriate package, then re-run this script:
  Debian / Ubuntu / Mint:  sudo apt install python3-venv
  Fedora / RHEL / CentOS:  sudo dnf install python3
  Arch / Manjaro:          sudo pacman -S python
  openSUSE:                sudo zypper install python3
  Alpine:                  sudo apk add python3
EOF
    exit 1
fi

mkdir -p "$CONFIG_DIR"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    echo "Creating venv at $VENV_DIR..."
    mkdir -p "$(dirname "$VENV_DIR")"
    python3 -m venv "$VENV_DIR"
fi

echo "Installing the monda package into $VENV_DIR..."
"$VENV_DIR/bin/pip" install --quiet --force-reinstall "$SCRIPT_DIR"

MONDA_BIN="$VENV_DIR/bin/monda"

ln -sf "$MONDA_BIN" /usr/local/bin/monda
echo "Linked: /usr/local/bin/monda -> $MONDA_BIN"

UNIT_PATH=/etc/systemd/system/monda.service
sed -e "s|%MONDA_BIN%|$MONDA_BIN|g" "$SCRIPT_DIR/monda.service" > "$UNIT_PATH"
echo "Installed unit file: $UNIT_PATH"

LOG_DIR=/var/log/monda
mkdir -p "$LOG_DIR/workers" "$LOG_DIR/jobs"
echo "Created log directory: $LOG_DIR"

LOGROTATE_PATH=/etc/logrotate.d/monda
install -m 0644 "$SCRIPT_DIR/logrotate/monda" "$LOGROTATE_PATH"
echo "Installed logrotate config: $LOGROTATE_PATH"

systemctl daemon-reload

if systemctl is-active --quiet monda; then
    echo "Restarting monda service to pick up new code..."
    systemctl restart monda
fi

cat <<EOF

Done. Next steps:
  1. Place your config at $CONFIG_FILE (see docs/config.md).
     Set LOG_DIR to $LOG_DIR if you want per-worker debug log files.
  2. systemctl enable --now monda
  3. monda logs                 # per-worker/job debug logs
     journalctl -u monda -f     # systemd stdout logs
  Log files under $LOG_DIR rotate daily; 30 days kept, gzip-compressed.
EOF
