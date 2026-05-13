import os

from monda.utils.logger import get_logger

logger = get_logger()


class Job:

    job_class_name = "Job"
    job_class_name_short = "J:"
    required_config_entries = []

    def __init__(self, name: str, job_config: dict):
        if "-" in self.job_class_name or '-' in name:
            logger.error("'-' is not allowed in job class names or job names.")
            os._exit(1)
        if not self.job_class_name.startswith("J_"):
            logger.error(f"Job class name must start with 'J_'. Offending name: {self.job_class_name}")
            os._exit(1)
        self.name = name
        self.config = job_config
        self.initialized = False

    def _work(self):
        logger.error(f"_work() method is not implemented in {self.__class__.__name__}")

    def _initialize(self):
        pass

    def initialize(self) -> bool:
        missing_entries = [k for k in self.required_config_entries if k not in self.config]
        if missing_entries:
            logger.error(f"Could not initialize: missing the following config entries: {missing_entries}")
            return False
        self.initialized = bool(self._initialize())
        return self.initialized

    def run(self) -> bool:
        if not self.initialized:
            logger.error(f"Could not run job '{self.name}': not initialized")
            return False
        logger.info(f"Job '{self.name}' starting")
        try:
            self._work()
        except Exception as e:
            logger.exception(f"Job '{self.name}' failed: {e}")
            return False
        logger.info(f"Job '{self.name}' finished")
        return True
