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

    _alert_states: frozenset[str] = frozenset({"exited", "dead", "restarting"})

    def _initialize(self) -> bool:
        self._last_alert: dict[str, float] = {}
        self._known_restart_counts: dict[str, int] = {}
        self._update_status("All containers healthy.")
        return True

    def _maybe_alert(self, key: str, message: str, target: str, now: float) -> None:
        if now - self._last_alert.get(key, 0.0) < 86400:
            return
        self._last_alert[key] = now
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

    def _restart_counts(self, names: list[str]) -> dict[str, int]:
        if not names:
            return {}
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.Name}}\t{{.RestartCount}}", *names],
            capture_output=True,
            text=True,
        )
        counts: dict[str, int] = {}
        for line in result.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) == 2:
                name = parts[0].lstrip("/")
                try:
                    counts[name] = int(parts[1])
                except ValueError:
                    pass
        return counts

    def _work(self) -> None:
        now = time.time()
        alert_target = self.config.get("ALERT_TARGET", "general")
        ignore: set[str] = set(self.config.get("IGNORE", []))

        try:
            states = self._container_states()
        except Exception as e:
            logger.error(f"Could not query Docker containers: {e}")
            return

        visible = [n for n in states if n not in ignore]

        try:
            restart_counts = self._restart_counts(visible)
        except Exception as e:
            logger.warning(f"Could not get Docker restart counts: {e}")
            restart_counts = {}

        problems: list[str] = []

        for name in visible:
            state = states[name]
            if state in self._alert_states:
                self._maybe_alert(name, f"Docker container '{name}' is {state}.", alert_target, now)
                problems.append(f"{name} ({state})")

        for name, count in restart_counts.items():
            prev = self._known_restart_counts.get(name)
            if prev is not None and count > prev:
                delta = count - prev
                self._maybe_alert(
                    f"{name}:restart",
                    f"Docker container '{name}' restarted {delta}x (total: {count}).",
                    alert_target, now,
                )
                if name not in [p.split(" ")[0] for p in problems]:
                    problems.append(f"{name} (restarted {delta}x)")

        self._known_restart_counts = restart_counts

        gone = set(self._last_alert) - {n for n in states} - {f"{n}:restart" for n in states}
        for key in gone:
            self._last_alert.pop(key)

        if problems:
            self._update_status(f"Issues: {', '.join(problems)}.", warning=True)
        else:
            self._update_status("All containers healthy.")
