import json
import logging
import os
import subprocess
import time
from datetime import datetime

from monda.classes.base.Worker import Worker
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger

logger: logging.Logger = get_logger()


# docs/workers.md
class W_BackupWatcherBorg(Worker):

    worker_class_name = "W_BackupWatcherBorg"
    worker_class_name_short = "W:BkpBorg"
    required_config_entries = ["BACKUPS"]

    def _initialize(self) -> bool:
        backups = self.config.get("BACKUPS", {})
        if not isinstance(backups, dict) or not backups:
            logger.error("BACKUPS must be a non-empty dict.")
            return False
        for name, spec in backups.items():
            for key in ("PATH", "EXPECTED_PERIOD_MINUTES", "PERMITTED_LAG_MINUTES"):
                if key not in spec:
                    logger.error(f"Backup '{name}' missing '{key}'.")
                    return False
        self._last_alert: dict[str, float] = {}
        self._update_status(f"Watching {len(backups)} backup(s).")
        return True

    def _maybe_alert(self, name: str, message: str, target: str, now: float) -> None:
        if now - self._last_alert.get(name, 0.0) < 86400:
            return
        self._last_alert[name] = now
        send_alert(message, target=target)

    def _borg_last_time(self, path: str, passphrase: str | None) -> float | None:
        env = os.environ.copy()
        if passphrase is not None:
            env["BORG_PASSPHRASE"] = passphrase
        result = subprocess.run(
            ["borg", "list", "--last", "1", "--json", path],
            capture_output=True,
            text=True,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        archives = json.loads(result.stdout).get("archives", [])
        if not archives:
            return None
        ts_str = archives[0]["start"].split(".")[0]
        return datetime.fromisoformat(ts_str).timestamp()

    def _work(self) -> None:
        now = time.time()
        alert_target = self.config.get("ALERT_TARGET", "general")
        overdue: list[str] = []
        for name, spec in self.config.get("BACKUPS", {}).items():
            path = spec["PATH"]
            deadline = now - (spec["EXPECTED_PERIOD_MINUTES"] + spec["PERMITTED_LAG_MINUTES"]) * 60
            try:
                last_ts = self._borg_last_time(path, spec.get("PASSPHRASE"))
            except Exception as e:
                logger.error(f"Backup '{name}': borg check failed: {e}")
                self._maybe_alert(name, f"Backup '{name}': borg check failed: {e}", alert_target, now)
                overdue.append(name)
                continue
            if last_ts is None:
                self._maybe_alert(name, f"Backup '{name}': no archives in {path}.", alert_target, now)
                overdue.append(name)
                continue
            if last_ts < deadline:
                last_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_ts))
                self._maybe_alert(name, f"Backup '{name}' overdue. Last backup: {last_str}.", alert_target, now)
                overdue.append(name)
            else:
                self._last_alert.pop(name, None)
                logger.debug(f"Backup '{name}' OK. Last backup: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(last_ts))}.")
        if overdue:
            self._update_status(f"Overdue: {', '.join(overdue)}.")
        else:
            self._update_status("All backups on time.")
