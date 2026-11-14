import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime
from typing import Callable

from monda.classes.base.Worker import Worker
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger

logger: logging.Logger = get_logger()

_AUDIT_ACCT_RE = re.compile(r'acct=(?:"([^"]+)"|([0-9A-Fa-f]{6,}))')
_AUDIT_ADDR_RE = re.compile(r'\baddr=(\S+)')
_SYSLOG_SSH_RE = re.compile(r'sshd\[\d+\]: Accepted \S+ for (\S+) from (\S+)')
_JCTL_ACCEPTED_RE = re.compile(r'Accepted \S+ for (\S+) from (\S+)')

_CANDIDATE_LOG_PATHS = [
    "/var/log/audit/audit.log",
    "/var/log/auth.log",
    "/var/log/secure",
]


def _decode_acct(m: re.Match) -> str:
    if m.group(1) is not None:
        return m.group(1)
    try:
        return bytes.fromhex(m.group(2)).decode("utf-8", errors="replace")
    except ValueError:
        return m.group(2)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_audit_line(line: str) -> tuple[str, str, str] | None:
    if "type=USER_LOGIN" not in line or "res=success" not in line or "sshd" not in line:
        return None
    acct_m = _AUDIT_ACCT_RE.search(line)
    addr_m = _AUDIT_ADDR_RE.search(line)
    return (
        _decode_acct(acct_m) if acct_m else "?",
        addr_m.group(1) if addr_m else "?",
        _now(),
    )


def _parse_syslog_line(line: str) -> tuple[str, str, str] | None:
    m = _SYSLOG_SSH_RE.search(line)
    return (m.group(1), m.group(2), _now()) if m else None


def _parse_jctl_event(event: dict) -> tuple[str, str, str] | None:
    m = _JCTL_ACCEPTED_RE.search(event.get("MESSAGE", ""))
    if not m:
        return None
    ts_us = event.get("__REALTIME_TIMESTAMP")
    try:
        ts = datetime.fromtimestamp(int(ts_us) / 1_000_000)
        timestamp = ts.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        timestamp = _now()
    return (m.group(1), m.group(2), timestamp)


# docs/workers.md
class W_SSHLoginWatcher(Worker):

    worker_class_name = "W_SSHLoginWatcher"
    worker_class_name_short = "W:SSHLogin"

    def _initialize(self) -> bool:
        self._alert_target: str = self.config.get("ALERT_TARGET", "general")
        log_path: str | None = self.config.get("LOG_PATH")

        if not log_path:
            log_path = next(
                (p for p in _CANDIDATE_LOG_PATHS if os.path.isfile(p) and os.access(p, os.R_OK)),
                None,
            )
            if log_path:
                logger.info(f"Auto-detected SSH log: {log_path}")

        if log_path:
            self._mode = "file"
            self._log_path: str = log_path
            self._parser: Callable[[str], tuple[str, str, str] | None] = (
                _parse_audit_line if "audit" in log_path else _parse_syslog_line
            )
            self._pos: int = 0
            self._inode: int | None = None
            try:
                st = os.stat(self._log_path)
                self._pos = st.st_size
                self._inode = st.st_ino
            except OSError:
                pass
            self._update_status(f"Watching {log_path}. No logins detected.")
            return True

        logger.info("No readable SSH log file found, falling back to journalctl.")
        self._mode = "journalctl"
        self._cursor_file: str = os.path.join(
            tempfile.gettempdir(),
            f"monda_ssh_cursor_{self._instance_name}",
        )
        r = subprocess.run(
            ["journalctl", "-u", "ssh", "-u", "sshd",
             "--output=json", "--no-pager", "-n", "0",
             f"--cursor-file={self._cursor_file}"],
            capture_output=True,
        )
        if r.returncode != 0:
            logger.error("journalctl is not available or failed. Cannot watch SSH logins.")
            return False
        self._update_status("Watching journalctl. No logins detected.")
        return True

    def _read_file_events(self) -> list[tuple[str, str, str]]:
        try:
            st = os.stat(self._log_path)
        except OSError as e:
            logger.warning(f"Cannot stat {self._log_path}: {e}")
            return []
        if st.st_ino != self._inode:
            self._pos = 0
            self._inode = st.st_ino
        elif st.st_size < self._pos:
            self._pos = 0
        if st.st_size == self._pos:
            return []
        try:
            with open(self._log_path, "r", encoding="utf-8", errors="replace") as f:
                f.seek(self._pos)
                chunk = f.read()
                self._pos = f.tell()
        except OSError as e:
            logger.warning(f"Cannot read {self._log_path}: {e}")
            return []
        return [r for line in chunk.splitlines() if (r := self._parser(line))]

    def _read_jctl_events(self) -> list[tuple[str, str, str]]:
        result = subprocess.run(
            ["journalctl", "-u", "ssh", "-u", "sshd",
             "--output=json", "--no-pager",
             f"--cursor-file={self._cursor_file}"],
            capture_output=True,
            text=True,
        )
        events = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            try:
                parsed = _parse_jctl_event(json.loads(line))
                if parsed:
                    events.append(parsed)
            except json.JSONDecodeError:
                continue
        return events

    def _work(self) -> None:
        events = self._read_file_events() if self._mode == "file" else self._read_jctl_events()
        for user, addr, ts in events:
            send_alert(f"SSH login: user '{user}' from {addr}.", target=self._alert_target)
            self._update_status(f"Last SSH login: '{user}' from {addr} at {ts}.")
