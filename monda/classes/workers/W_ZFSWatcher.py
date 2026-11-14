import logging
import re
import shutil
import subprocess
import time

from monda.classes.base.Worker import Worker
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger

logger: logging.Logger = get_logger()

_OK_STATES = frozenset({"ONLINE", "AVAIL"})
_SCAN_RE = re.compile(r"\b(scrub|resilver)\b.*\bin progress\b", re.IGNORECASE)
_POOL_RE = re.compile(r"^  pool:\s+(\S+)\s*$")
_STATE_RE = re.compile(r"^ state:\s+(\S+)\s*$")
_ERRORS_RE = re.compile(r"^errors:\s+(.+)$")
_VDEV_RE = re.compile(
    r"^\s+(\S+)\s+(ONLINE|DEGRADED|FAULTED|OFFLINE|UNAVAIL|REMOVED|AVAIL)"
    r"\s+(\d+)\s+(\d+)\s+(\d+)\b"
)


# docs/workers.md
class W_ZFSWatcher(Worker):

    worker_class_name = "W_ZFSWatcher"
    worker_class_name_short = "W:ZFS"

    def _initialize(self) -> bool:
        if shutil.which("zpool") is None:
            logger.error("zpool binary not found on PATH.")
            return False
        self._last_alert: dict[str, float] = {}
        try:
            pools = self._parse_status()
            self._prev_scan: dict[str, str | None] = {
                name: info["scan"] for name, info in pools.items()
            }
            count = len(pools)
            self._update_status(
                f"Watching {count} ZFS pool{'s' if count != 1 else ''}."
                if count else "No ZFS pools detected."
            )
        except Exception as e:
            logger.error(f"Could not query ZFS pools: {e}")
            self._prev_scan = {}
            self._update_status("Watching ZFS pools.")
        return True

    def _maybe_alert(self, key: str, message: str, target: str, now: float) -> None:
        if now - self._last_alert.get(key, 0.0) < 86400:
            return
        self._last_alert[key] = now
        send_alert(message, target=target)

    def _parse_status(self) -> dict[str, dict]:
        """Auto-detect all imported ZFS pools via `zpool status`."""
        result = subprocess.run(
            ["zpool", "status"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
            # No pools imported is not an error condition.
            if "no pools available" in err.lower():
                return {}
            raise RuntimeError(err)

        pools: dict[str, dict] = {}
        current: str | None = None
        in_config = False

        for line in result.stdout.splitlines():
            pool_m = _POOL_RE.match(line)
            if pool_m:
                current = pool_m.group(1)
                pools[current] = {
                    "health": "UNKNOWN",
                    "devices": [],
                    "errors": None,
                    "scan": None,
                }
                in_config = False
                continue

            if current is None:
                continue

            state_m = _STATE_RE.match(line)
            if state_m:
                pools[current]["health"] = state_m.group(1)
                continue

            if line.startswith("config:"):
                in_config = True
                continue

            if line.startswith("errors:"):
                in_config = False
                err_m = _ERRORS_RE.match(line)
                if err_m:
                    msg = err_m.group(1).strip()
                    if msg.lower() != "no known data errors":
                        pools[current]["errors"] = msg
                continue

            scan_m = _SCAN_RE.search(line)
            if scan_m and "scan:" in line:
                pools[current]["scan"] = scan_m.group(1).lower()
                continue

            if not in_config:
                continue

            # Skip header / blank / pool root row (same name as pool)
            vdev_m = _VDEV_RE.match(line)
            if not vdev_m:
                continue
            name, state, read, write, cksum = vdev_m.groups()
            if name == current:
                continue
            pools[current]["devices"].append({
                "name": name,
                "state": state,
                "read": int(read),
                "write": int(write),
                "cksum": int(cksum),
            })

        return pools

    def _work(self) -> None:
        now = time.time()
        target = self.config.get("ALERT_TARGET", "general")
        ignore: set[str] = set(self.config.get("IGNORE", []))

        try:
            pools = self._parse_status()
        except Exception as e:
            logger.error(f"Could not query ZFS pools: {e}")
            return

        unhealthy: set[str] = set()

        for name, info in pools.items():
            if name in ignore:
                continue

            health = info["health"]
            if health != "ONLINE":
                self._maybe_alert(
                    f"{name}:health",
                    f"zfs: pool {name} is {health}.",
                    target, now,
                )
                unhealthy.add(name)
            else:
                self._last_alert.pop(f"{name}:health", None)

            if info["errors"]:
                self._maybe_alert(
                    f"{name}:errors",
                    f"zfs: pool {name} reports errors: {info['errors']}",
                    target, now,
                )
                unhealthy.add(name)
            else:
                self._last_alert.pop(f"{name}:errors", None)

            for dev in info["devices"]:
                key = f"{name}:{dev['name']}"
                bad_state = dev["state"] not in _OK_STATES
                bad_io = (dev["read"] + dev["write"] + dev["cksum"]) > 0
                if bad_state or bad_io:
                    parts = []
                    if bad_state:
                        parts.append(dev["state"])
                    if bad_io:
                        parts.append(
                            f"r/w/c={dev['read']}/{dev['write']}/{dev['cksum']}"
                        )
                    detail = ", ".join(parts)
                    self._maybe_alert(
                        f"{key}:device",
                        f"zfs: {dev['name']} in {name} is unhealthy ({detail}).",
                        target, now,
                    )
                    unhealthy.add(name)
                else:
                    self._last_alert.pop(f"{key}:device", None)

            prev = self._prev_scan.get(name)
            curr = info["scan"]
            if curr and not prev:
                send_alert(f"zfs: {curr} started on {name}.", target=target)
            elif prev and not curr:
                send_alert(f"zfs: {prev} finished on {name}.", target=target)
            self._prev_scan[name] = curr

        for gone in set(self._prev_scan) - set(pools):
            prefix = f"{gone}:"
            for key in list(self._last_alert):
                if key.startswith(prefix) or key == f"{gone}:health" or key == f"{gone}:errors":
                    self._last_alert.pop(key, None)
            self._prev_scan.pop(gone, None)

        total = len([n for n in pools if n not in ignore])
        healthy = total - len(unhealthy)
        self._update_status(
            f"{healthy}/{total} pools healthy.",
            error=bool(unhealthy),
        )
