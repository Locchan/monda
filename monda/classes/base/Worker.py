import logging
import os
import time
from threading import Thread

from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger
from monda.utils.misc import read_config
from monda.utils.status import WorkerEntry, get_or_create_worker

logger: logging.Logger = get_logger()

class Worker:

    worker_class_name: str = "Worker"
    worker_class_name_short: str = "W:"
    required_config_entries: list[str] = []

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
        self._status_entry: WorkerEntry | None = None

    def _work(self) -> None:
        logger.error(f"_work() method is not implemented in {self.__class__.__name__}")
        pass

    def _initialize(self) -> None:
        pass

    def _update_status(self, detail: str) -> None:
        if self._status_entry is not None:
            self._status_entry.detail = detail

    def initialize(self) -> bool:
        entry, is_new = get_or_create_worker(self.name)
        if not is_new:
            entry.last_restart_at = time.time()
            entry.restart_count += 1
            entry.crashed_at = None
            entry.crash_error = None
            entry.detail = "Starting..."
        self._status_entry = entry

        worker_config = read_config().get("WORKER_CONFIG", {})
        instance_config = worker_config.get(self.worker_class_name, {}).get(self._instance_name)
        if instance_config is None:
            logger.error("Could not initialize: no config.")
            entry.crashed_at = time.time()
            entry.crash_error = "No config."
            return False
        missing_entries = [k for k in self.required_config_entries if k not in instance_config]
        if missing_entries:
            logger.error(f"Could not initialize: missing the following config entries: {missing_entries}")
            entry.crashed_at = time.time()
            entry.crash_error = f"Missing config: {missing_entries}"
            return False
        self.config = instance_config
        self.initialized = bool(self._initialize())
        if not self.initialized:
            entry.crashed_at = time.time()
            entry.crash_error = "Initialization failed."
        return self.initialized

    def _refresh_config(self) -> None:
        instance_config = (read_config()
                           .get("WORKER_CONFIG", {})
                           .get(self.worker_class_name, {})
                           .get(self._instance_name, {}))
        if instance_config:
            self.config = instance_config

    def _run(self) -> None:
        if self._status_entry is not None:
            self._status_entry.detail = "Running."
        try:
            while True:
                self._refresh_config()
                self._work()
                time.sleep(self.interval)
        except BaseException as e:
            logger.error(f"Crashed with an exception: {e}")
            logger.error(str(e))
            if self._status_entry is not None:
                self._status_entry.crashed_at = time.time()
                self._status_entry.crash_error = str(e)
            send_alert(f"Worker {self.name} crashed. Check monda logs.", target="general")

    def run(self) -> Thread | None:
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
