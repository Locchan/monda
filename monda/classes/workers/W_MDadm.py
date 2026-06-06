import logging
import re
import time

from monda.classes.base.Worker import Worker
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger

logger: logging.Logger = get_logger()


# docs/workers.md
class W_MDadm(Worker):

    worker_class_name = "W_MDadm"
    worker_class_name_short = "W:MDadm"

    def _initialize(self) -> bool:
        self._last_alert: dict[str, float] = {}
        path = self.config.get("MDSTAT_PATH", "/proc/mdstat")
        try:
            arrays = self._parse_mdstat(path)
            # Seed sync state so we don't fire "started" alerts on first tick
            # for syncs already in progress before monda launched.
            self._prev_syncing: dict[str, str | None] = {
                name: info["syncing"] for name, info in arrays.items()
            }
        except Exception:
            self._prev_syncing = {}
        self._update_status("Watching md arrays.")
        return True

    def _maybe_alert(self, key: str, message: str, target: str, now: float) -> None:
        if now - self._last_alert.get(key, 0.0) < 86400:
            return
        self._last_alert[key] = now
        send_alert(message, target=target)

    def _parse_mdstat(self, path: str) -> dict[str, dict]:
        with open(path) as f:
            content = f.read()

        arrays: dict[str, dict] = {}
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            m = re.match(r'^(md\S+)\s*:\s*(\w+)', lines[i])
            if not m:
                i += 1
                continue

            name, state = m.group(1), m.group(2)
            info: dict = {"state": state, "failed_drives": 0, "syncing": None}
            j = i + 1
            while j < len(lines):
                sub = lines[j]
                if not sub or re.match(r'^(md\S+\s*:|Personalities|unused)', sub):
                    break
                # [UU_U] pattern — underscores are missing/failed drives
                bracket = re.search(r'\[([U_]+)\]', sub)
                if bracket:
                    info["failed_drives"] = bracket.group(1).count("_")
                # resync / recovery / check / repair progress line
                sync = re.search(r'\[[\s=>\.]+ \]\s+(\w+)\s*=\s*[\d.]+%', sub)
                if not sync:
                    sync = re.search(r'\[[\s=>\.]+\]\s+(\w+)\s*=\s*[\d.]+%', sub)
                if sync:
                    info["syncing"] = sync.group(1)
                j += 1

            arrays[name] = info
            i = j

        return arrays

    def _work(self) -> None:
        now = time.time()
        target = self.config.get("ALERT_TARGET", "general")
        path = self.config.get("MDSTAT_PATH", "/proc/mdstat")

        try:
            arrays = self._parse_mdstat(path)
        except Exception as e:
            logger.error(f"Could not read mdstat at '{path}': {e}")
            return

        problems: list[str] = []

        for name, info in arrays.items():
            # Drive failure — persistent state, re-alert every 24 h
            failed = info["failed_drives"]
            if failed > 0:
                self._maybe_alert(
                    f"{name}:failed",
                    f"mdadm: {failed} drive(s) failed in {name}.",
                    target, now,
                )
                problems.append(f"{name}: {failed} drive(s) failed")
            else:
                self._last_alert.pop(f"{name}:failed", None)

            # Inactive / inconsistent array — persistent, re-alert every 24 h
            if info["state"] == "inactive":
                self._maybe_alert(
                    f"{name}:inactive",
                    f"mdadm: array {name} is inactive.",
                    target, now,
                )
                problems.append(f"{name}: inactive")
            else:
                self._last_alert.pop(f"{name}:inactive", None)

            # Resync transitions — fire once per start/end event
            prev = self._prev_syncing.get(name)
            curr = info["syncing"]
            if curr and not prev:
                send_alert(f"mdadm: {curr} started on {name}.", target=target)
            elif prev and not curr:
                send_alert(f"mdadm: {prev} finished on {name}.", target=target)
            self._prev_syncing[name] = curr

        # Clean up state for arrays that disappeared from mdstat
        for gone in set(self._prev_syncing) - set(arrays):
            self._last_alert.pop(f"{gone}:failed", None)
            self._last_alert.pop(f"{gone}:inactive", None)
            self._prev_syncing.pop(gone, None)

        if problems:
            self._update_status(f"Issues: {', '.join(problems)}.", warning=True)
        else:
            syncing = [f"{n} ({v['syncing']})" for n, v in arrays.items() if v["syncing"]]
            self._update_status(
                f"Syncing: {', '.join(syncing)}." if syncing else "All arrays healthy."
            )
