import logging
import os
import time
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
    required_config_entries: list[str] = []
    disabled_jobs: list[type] = []

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

        schema = JOB_SCHEMAS.get(self.job_class_name)
        if schema:
            errors = validate(self.config, schema.fields)
        else:
            errors = [f"'{k}' is required" for k in self.required_config_entries if k not in self.config]
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
