import os
import time
from threading import Thread

from monda.utils.logger import get_logger
from monda.utils.misc import read_config

logger = get_logger()


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

    job_class_name = "Job"
    job_class_name_short = "J:"
    required_config_entries = []

    def __init__(self, name: str, job_config: dict | None = None):
        if "-" in self.job_class_name or '-' in name:
            logger.error("'-' is not allowed in job class names or job names.")
            os._exit(1)
        if not self.job_class_name.startswith("J_"):
            logger.error(f"Job class name must start with 'J_'. Offending name: {self.job_class_name}")
            os._exit(1)
        self.name = name
        self._runtime_config = job_config or {}
        self.config = {}
        self.initialized = False

    def _work(self):
        logger.error(f"_work() method is not implemented in {self.__class__.__name__}")

    def _initialize(self):
        pass

    def initialize(self) -> bool:
        static_config = (read_config()
                         .get("JOB_CONFIG", {})
                         .get(self.job_class_name, {})
                         .get(self.name, {}))
        self.config = {**static_config, **self._runtime_config}
        missing_entries = [k for k in self.required_config_entries if k not in self.config]
        if missing_entries:
            logger.error(f"Could not initialize: missing the following config entries: {missing_entries}")
            return False
        self.initialized = bool(self._initialize())
        return self.initialized

    def _run(self) -> None:
        logger.info(f"[{self.__class__.__name__}] '{self.name}' starting...")
        started = time.monotonic()
        try:
            self._work()
        except Exception as e:
            elapsed = _format_duration(time.monotonic() - started)
            logger.exception(f"Job '{self.name}' failed after {elapsed}: {e}")
            return
        elapsed = _format_duration(time.monotonic() - started)
        logger.info(f"Job '{self.name}' finished in {elapsed}")

    def run(self) -> Thread | None:
        if not self.initialized:
            logger.error(f"Could not run [{self.__class__.__name__}] '{self.name}': not initialized")
            return None
        try:
            job_thread = Thread(target=self._run, daemon=True, name=f"{self.job_class_name_short}-{self.name}")
            job_thread.start()
            return job_thread
        except BaseException as e:
            logger.error(f"Could not create job thread for [{self.__class__.__name__}] '{self.name}': {e}")
            return None
