import logging
import os
import shutil
import time
from pathlib import Path
from threading import Thread

from monda.config_schema import JOB_SCHEMAS, validate
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger
from monda.utils.misc import read_config
from monda.utils.status import get_or_create_job

logger: logging.Logger = get_logger()


def _format_duration(seconds: float) -> str:
    if seconds < 3:
        return f"{seconds * 1000:.0f}ms"
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}h")
    if m or h:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


class Job:

    job_class_name: str = "Job"
    job_class_name_short: str = "J:"
    disabled_jobs: list[type] = []
    # Sliding-window trigger timestamps keyed by "JobClass/instance".
    _trigger_times: dict[str, list[float]] = {}

    def __init__(self, name: str, job_config: dict | None = None, silent: bool = False) -> None:
        if "-" in self.job_class_name or '-' in name:
            logger.error("'-' is not allowed in job class names or job names.")
            os._exit(1)
        if not self.job_class_name.startswith("J_"):
            logger.error(f"Job class name must start with 'J_'. Offending name: {self.job_class_name}")
            os._exit(1)
        self._instance_name = name
        self.name = f"{self.job_class_name_short}_{name}"
        self._runtime_config = job_config or {}
        self.silent = silent
        self.config = {}
        self.initialized = False

    def _info(self, message: str) -> None:
        if self.silent:
            logger.debug(message)
        else:
            logger.info(message)

    def _work(self) -> None:
        logger.error(f"_work() method is not implemented in {self.__class__.__name__}")

    def _initialize(self) -> None:
        pass

    def _trigger_key(self) -> str:
        return f"{self.job_class_name}/{self._instance_name}"

    def _record_trigger_and_maybe_alert(self) -> None:
        """If LED_THRESHOLD + LED_THRESHOLD_PERIOD_SEC are set, track runs and alert on excess."""
        raw_threshold = self.config.get("LED_THRESHOLD")
        raw_period = self.config.get("LED_THRESHOLD_PERIOD_SEC")
        if raw_threshold is None and raw_period is None:
            return
        if raw_threshold is None or raw_period is None:
            logger.error(
                f"{self.name}: LED_THRESHOLD and LED_THRESHOLD_PERIOD_SEC must be set together."
            )
            return
        try:
            threshold = int(raw_threshold)
            period = float(raw_period)
        except (TypeError, ValueError):
            logger.error(
                f"{self.name}: LED_THRESHOLD / LED_THRESHOLD_PERIOD_SEC must be numbers."
            )
            return
        if threshold < 0 or period <= 0:
            logger.error(
                f"{self.name}: LED_THRESHOLD must be >= 0 and LED_THRESHOLD_PERIOD_SEC > 0."
            )
            return

        now = time.monotonic()
        key = self._trigger_key()
        times = [t for t in self._trigger_times.get(key, []) if now - t <= period]
        times.append(now)
        self._trigger_times[key] = times
        count = len(times)
        if count > threshold:
            period_s = int(period) if period == int(period) else period
            send_alert(
                f"{self.name}: Triggered {count} times in last {period_s} seconds.",
                target="general",
            )

    def _store_or_alert(
        self,
        path: str,
        *,
        message: str,
        led_target: str = "camera_alerts",
    ) -> None:
        """Deliver media via LED alert (MODE=LED) or write under STOREDIR (MODE=STORE).

        STORE layout: ``STOREDIR/<JobClass>/<instance>/<basename>``
        e.g. ``STOREDIR/J_HikAlertSnap/cam_1/<file>.jpg``.
        """
        mode = str(self.config.get("MODE", "LED")).upper()
        if mode == "STORE":
            store_root = self.config.get("STOREDIR")
            if not store_root:
                raise RuntimeError("MODE=STORE requires STOREDIR.")
            dest_dir = Path(store_root) / self.job_class_name / self._instance_name
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / Path(path).name
            shutil.move(path, dest)
            self._info(f"Stored {dest}")
            return
        if mode != "LED":
            raise RuntimeError(f"Unknown MODE {mode!r} (expected LED or STORE).")
        send_alert(message, target=led_target, files=[path])

    def initialize(self) -> bool:
        job_type_config = (read_config()
                           .get("JOB_CONFIG", {})
                           .get(self.job_class_name, {}))
        static_config = job_type_config.get(self._instance_name, {})
        self.config = {**static_config, **self._runtime_config}

        enabled_in_config = job_type_config.get("ENABLED", True)
        if not enabled_in_config:
            if self.__class__ not in self.disabled_jobs:
                self.disabled_jobs.append(self.__class__)
                logger.info(f"[{self.__class__.__name__}] has been disabled.")
        else:
            if self.__class__ in self.disabled_jobs:
                self.disabled_jobs.remove(self.__class__)
                logger.info(f"[{self.__class__.__name__}] has been enabled.")

        if self.__class__ in self.disabled_jobs:
            return True

        schema = JOB_SCHEMAS[self.job_class_name]
        errors = validate(self.config, schema.fields)
        if errors:
            msg = "; ".join(errors)
            logger.error(f"Config validation failed for {self.job_class_name}/{self._instance_name}: {msg}")
            return False
        self.initialized = bool(self._initialize())
        return self.initialized

    def _run(self) -> None:
        entry = get_or_create_job(f"{self.job_class_name}/{self._instance_name}")
        entry.run_count += 1
        entry.last_run_at = time.time()
        self._record_trigger_and_maybe_alert()

        self._info(f"'{self.name}' starting...")
        started = time.monotonic()
        try:
            self._work()
        except Exception as e:
            elapsed = time.monotonic() - started
            elapsed_str = _format_duration(elapsed)
            entry.last_run_ok = False
            entry.last_run_duration = elapsed
            entry.detail = f"Failed after {elapsed_str}: {e}"
            logger.exception(f"'{self.name}' failed after {elapsed_str}: {e}")
            send_alert(f"Job {self.name} failed. Check monda logs.", target="general")
            return
        elapsed = time.monotonic() - started
        elapsed_str = _format_duration(elapsed)
        entry.last_run_ok = True
        entry.last_run_duration = elapsed
        entry.detail = f"Last run: success, took {elapsed_str}."
        self._info(f"'{self.name}' finished in {elapsed_str}")

    def run(self) -> Thread | None:
        if self.__class__ in self.disabled_jobs:
            return None
        if not self.initialized:
            logger.error(f"Could not run '{self.name}': not initialized")
            return None
        try:
            job_thread = Thread(target=self._run, daemon=True, name=self.name)
            job_thread.start()
            return job_thread
        except BaseException as e:
            logger.error(f"Could not create job thread for '{self.name}': {e}")
            return None
