import logging
import os
import time
from threading import Thread

from monda.config_schema import WORKER_SCHEMAS, validate
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger
from monda.utils.misc import read_config
from monda.utils.status import (
    WorkerEntry,
    consume_pending_sleep,
    get_or_create_worker,
    mark_config_reload,
    remove_worker,
)

logger: logging.Logger = get_logger()

# Max uninterrupted sleep between config-change checks (when watching).
_SLEEP_CHUNK_S = 5.0


class Worker:

    worker_class_name: str = "Worker"
    worker_class_name_short: str = "W:"
    # When True, config-slice changes restart the worker; ENABLED false stops it.
    # W_ConfigWatch sets this False.
    watch_config_changes: bool = True

    def __init__(self, name: str, interval_s: int) -> None:
        if "-" in self.worker_class_name or '-' in name:
            logger.error("'-' is not allowed in worker class names or worker names.")
            os._exit(1)
        if not self.worker_class_name.startswith("W_"):
            logger.error(f"Worker class name must start with 'W_'. Offending name: {self.worker_class_name}")
            os._exit(1)
        self._instance_name = name
        self.name = f"{self.worker_class_name_short}_{name}"
        self.interval = interval_s
        self.config = {}
        self.initialized = False
        self._disabled = False
        self._status_entry: WorkerEntry | None = None

    def _work(self) -> None:
        logger.error(f"_work() method is not implemented in {self.__class__.__name__}")
        pass

    def _initialize(self) -> None:
        pass

    def _update_status(self, detail: str, warning: bool = False, error: bool = False) -> None:
        if self._status_entry is not None:
            self._status_entry.detail = detail
            self._status_entry.warning = warning
            self._status_entry.error = error

    def _purge_status(self) -> None:
        remove_worker(self.name)
        self._status_entry = None

    def initialize(self, config_reload: bool = False) -> bool:
        entry, is_new = get_or_create_worker(self.name)
        if not is_new:
            entry.crashed_at = None
            entry.crash_error = None
            entry.warning = False
            entry.error = False
            # Config-driven restarts are intentional — don't mark as crash recovery
            # and keep the previous status detail (e.g. mid-sleep resume).
            if not config_reload:
                entry.last_restart_at = time.time()
                entry.restart_count += 1
                entry.detail = "Starting..."
        self._status_entry = entry

        worker_config = read_config().get("WORKER_CONFIG", {})
        instance_config = worker_config.get(self.worker_class_name, {}).get(self._instance_name)
        if instance_config is None:
            logger.error("Could not initialize: no config.")
            entry.detail = "No config."
            entry.crashed_at = time.time()
            entry.crash_error = "No config."
            return False
        schema = WORKER_SCHEMAS[self.worker_class_name]
        errors = validate(instance_config, schema.fields)
        if errors:
            msg = "; ".join(errors)
            logger.error(f"Config validation failed for {self.worker_class_name}/{self._instance_name}: {msg}")
            entry.detail = "Config validation failed."
            entry.crashed_at = time.time()
            entry.crash_error = f"Config error: {msg}"
            return False
        if not instance_config.get("ENABLED", True):
            logger.info(f"Worker {self.worker_class_name}/{self._instance_name} is disabled.")
            self._disabled = True
            self._purge_status()
            return True
        self.config = instance_config
        self.initialized = bool(self._initialize())
        if not self.initialized:
            entry.detail = "Initialization failed."
            entry.crashed_at = time.time()
            entry.crash_error = "Initialization failed."
        return self.initialized

    def _refresh_config(self) -> str:
        """Re-read this worker's config slice.

        Returns:
            "ok" — unchanged (or watching disabled for this worker class)
            "changed" — slice differs; caller should restart
            "disabled" — ENABLED is false or instance removed; caller should stop
        """
        if not self.watch_config_changes:
            return "ok"

        instance_config = (read_config()
                           .get("WORKER_CONFIG", {})
                           .get(self.worker_class_name, {})
                           .get(self._instance_name))
        if instance_config is None or not instance_config.get("ENABLED", True):
            return "disabled"
        if instance_config != self.config:
            return "changed"
        return "ok"

    def _sleep_until(self, deadline: float) -> str:
        """Sleep until a monotonic deadline without drifting from check overhead.

        If the deadline is already in the past (overslept), returns "ok"
        immediately so the tick can launch right away.

        When config watching is on and more than 5s remain, sleeps in ≤5s chunks
        and re-checks for config changes between chunks. Returns the same action
        codes as `_refresh_config`, or "ok" when the deadline is reached.
        """
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "ok"
            if not self.watch_config_changes or remaining <= _SLEEP_CHUNK_S:
                time.sleep(remaining)
                return "ok"
            time.sleep(_SLEEP_CHUNK_S)
            action = self._refresh_config()
            if action != "ok":
                return action

    def _stop_for_config(self, action: str, sleep_until: float | None = None) -> bool:
        """Handle disabled/changed. Returns True if `_run` should exit."""
        if action == "ok":
            return False
        if action == "disabled":
            logger.info(f"Worker {self.name} disabled in config, stopping.")
            self._purge_status()
            return True
        # changed
        logger.info(f"Worker {self.name} config changed, restarting.")
        pending = sleep_until if sleep_until is not None and sleep_until > time.monotonic() else None
        mark_config_reload(self.worker_class_name, self._instance_name, sleep_until=pending)
        target = self.config.get("ALERT_TARGET", "general")
        send_alert(
            f"Worker {self.name} restarted due to configuration change.",
            target=target,
        )
        return True

    def _run(self) -> None:
        try:
            # Resume an interrupted inter-tick sleep after a config-change restart.
            resume_deadline = consume_pending_sleep(self.worker_class_name, self._instance_name)
            if resume_deadline is not None:
                next_due = resume_deadline
            else:
                next_due = time.monotonic()
                if self._status_entry is not None:
                    self._status_entry.detail = "Running."

            while True:
                # Overslept → _sleep_until returns immediately → tick starts now.
                action = self._sleep_until(next_due)
                if self._stop_for_config(action, sleep_until=next_due):
                    return

                action = self._refresh_config()
                if self._stop_for_config(action):
                    return

                interval = max(float(self.interval), 0.0)
                # Next deadline is fixed at work start: last deadline + period.
                next_due = next_due + interval
                self._work()

                # Finished after that deadline → error, reschedule from now.
                if interval > 0 and time.monotonic() >= next_due:
                    logger.error(
                        f"Worker {self.name} finished after its next deadline; "
                        f"rescheduling from now."
                    )
                    if self._status_entry is not None:
                        self._status_entry.error = True
                    target = self.config.get("ALERT_TARGET", "general")
                    send_alert(
                        f"Worker {self.name} overlapped its scheduled deadline; "
                        f"rescheduled.",
                        target=target,
                    )
                    next_due = time.monotonic() + interval
        except BaseException as e:
            logger.error(f"Crashed with an exception: {e}")
            logger.error(str(e))
            if self._status_entry is not None:
                self._status_entry.crashed_at = time.time()
                self._status_entry.crash_error = str(e)
            send_alert(f"Worker {self.name} crashed. Check monda logs.", target="general")

    def run(self) -> Thread | None:
        if self._disabled:
            return None
        if not self.initialized:
            logger.error(f"Could not start worker {self.name}: not initialized")
            return None
        try:
            worker_thread = Thread(target=self._run, daemon=True, name=self.name)
            worker_thread.start()
            logger.info(f"Started thread '{worker_thread.name}'")
            return worker_thread
        except BaseException as e:
            logger.error(f"Could not create worker thread: {e}")
            return None
