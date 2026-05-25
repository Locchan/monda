import logging
import subprocess
import time

from monda.classes.base.Worker import Worker
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger

logger: logging.Logger = get_logger()


# docs/workers.md
class W_SystemdWatcher(Worker):

    worker_class_name = "W_SystemdWatcher"
    worker_class_name_short = "W:Systemd"
    required_config_entries = []

    def _initialize(self) -> bool:
        self._last_alert: dict[str, float] = {}
        return True

    def _maybe_alert(self, name: str, message: str, target: str, now: float) -> None:
        if now - self._last_alert.get(name, 0.0) < 86400:
            return
        self._last_alert[name] = now
        send_alert(message, target=target)

    def _failed_services(self) -> list[str]:
        result = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=failed",
             "--no-pager", "--plain", "--no-legend"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        return [line.split()[0] for line in result.stdout.splitlines() if line.split()]

    def _work(self) -> None:
        now = time.time()
        alert_target = self.config.get("ALERT_TARGET", "general")
        ignore: set[str] = set(self.config.get("IGNORE", []))
        try:
            failed = set(self._failed_services()) - ignore
        except Exception as e:
            logger.error(f"Could not query systemd units: {e}")
            return
        for service in failed:
            self._maybe_alert(service, f"Systemd service '{service}' has failed.", alert_target, now)
        for service in list(self._last_alert):
            if service not in failed:
                self._last_alert.pop(service)
