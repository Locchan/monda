import logging
import os
import time

from monda.classes.base.Worker import Worker
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger

logger: logging.Logger = get_logger()


# docs/workers.md
class W_BackupWatcherRaw(Worker):

    worker_class_name = "W_BackupWatcherRaw"
    worker_class_name_short = "W:BkpRaw"
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
            if not os.path.isdir(spec["PATH"]):
                logger.warning(f"Backup path for '{name}' does not exist: {spec['PATH']}")
        self._last_alert: dict[str, float] = {}
        return True

    def _maybe_alert(self, name: str, message: str, target: str, now: float) -> None:
        if now - self._last_alert.get(name, 0.0) < 86400:
            return
        self._last_alert[name] = now
        send_alert(message, target=target)

    def _newest_mtime(self, path: str) -> float | None:
        newest: float | None = None
        for dirpath, _, filenames in os.walk(path):
            for fname in filenames:
                try:
                    mtime = os.stat(os.path.join(dirpath, fname)).st_mtime
                except OSError:
                    continue
                if newest is None or mtime > newest:
                    newest = mtime
        return newest

    def _work(self) -> None:
        now = time.time()
        alert_target = self.config.get("ALERT_TARGET", "general")
        for name, spec in self.config.get("BACKUPS", {}).items():
            path = spec["PATH"]
            deadline = now - (spec["EXPECTED_PERIOD_MINUTES"] + spec["PERMITTED_LAG_MINUTES"]) * 60
            newest = self._newest_mtime(path)
            if newest is None:
                self._maybe_alert(name, f"Backup '{name}': no files found in {path}.", alert_target, now)
                continue
            if newest < deadline:
                last_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest))
                self._maybe_alert(name, f"Backup '{name}' overdue. Last file: {last_str}.", alert_target, now)
            else:
                self._last_alert.pop(name, None)
                logger.debug(f"Backup '{name}' OK. Last file: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(newest))}.")
