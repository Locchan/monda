import json
import logging
import subprocess
import time

from monda.classes.base.Worker import Worker
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger

logger: logging.Logger = get_logger()


# docs/workers.md
class W_DockerWatcher(Worker):

    worker_class_name = "W_DockerWatcher"
    worker_class_name_short = "W:Docker"
    required_config_entries = []

    _alert_states: frozenset[str] = frozenset({"exited", "dead"})

    def _initialize(self) -> bool:
        self._last_alert: dict[str, float] = {}
        self._update_status("All containers healthy.")
        return True

    def _maybe_alert(self, name: str, message: str, target: str, now: float) -> None:
        if now - self._last_alert.get(name, 0.0) < 86400:
            return
        self._last_alert[name] = now
        send_alert(message, target=target)

    def _container_states(self) -> dict[str, str]:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
        containers: dict[str, str] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            containers[data["Names"]] = data["State"]
        return containers

    def _work(self) -> None:
        now = time.time()
        alert_target = self.config.get("ALERT_TARGET", "general")
        ignore: set[str] = set(self.config.get("IGNORE", []))
        try:
            states = self._container_states()
        except Exception as e:
            logger.error(f"Could not query Docker containers: {e}")
            return
        unhealthy = {
            name: state for name, state in states.items()
            if state in self._alert_states and name not in ignore
        }
        for name, state in unhealthy.items():
            self._maybe_alert(name, f"Docker container '{name}' is {state}.", alert_target, now)
        for name in list(self._last_alert):
            if name not in unhealthy:
                self._last_alert.pop(name)
        if unhealthy:
            parts = [f"{n} ({s})" for n, s in sorted(unhealthy.items())]
            self._update_status(f"Unhealthy: {', '.join(parts)}.")
        else:
            self._update_status("All containers healthy.")
