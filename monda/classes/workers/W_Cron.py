import logging
from datetime import datetime

from croniter import croniter

from monda.classes.base.Worker import Worker
from monda.classes.jobs import ENABLED_JOBS
from monda.utils.logger import get_logger
from monda.utils.status import get_or_create_job

logger: logging.Logger = get_logger()


# docs/workers.md
class W_Cron(Worker):

    worker_class_name = "W_Cron"
    worker_class_name_short = "W:Cron"

    required_config_entries = ["JOBS"]

    def __init__(self, name: str, interval_s: int) -> None:
        super().__init__(name, interval_s)
        self._last_check: datetime | None = None

    def _initialize(self) -> bool:
        jobs = self.config.get("JOBS", {})
        if not isinstance(jobs, dict) or not jobs:
            logger.error("W_Cron JOBS must be a non-empty dict.")
            return False
        for job_name, spec in jobs.items():
            schedule = spec.get("SCHEDULE")
            job_class_name = spec.get("JOB_CLASS")
            if not schedule:
                logger.error(f"W_Cron job '{job_name}' missing SCHEDULE.")
                return False
            if not job_class_name:
                logger.error(f"W_Cron job '{job_name}' missing JOB_CLASS.")
                return False
            if not croniter.is_valid(schedule):
                logger.error(f"W_Cron job '{job_name}' has invalid schedule: {schedule!r}")
                return False
            if job_class_name not in ENABLED_JOBS:
                logger.error(f"W_Cron job '{job_name}' references unknown JOB_CLASS: {job_class_name!r}")
                return False
        self._last_check = datetime.now()
        self._update_status(f"Scheduled {len(jobs)} job(s).")
        return True

    def _spawn_job(self, job_name: str, job_class_name: str, params: dict, silent: bool) -> None:
        job_cls = ENABLED_JOBS.get(job_class_name)
        if job_cls is None:
            logger.warning(f"W_Cron: unknown job class '{job_class_name}' for '{job_name}'")
            return
        job = job_cls(job_name, params, silent=silent)
        if job.initialize():
            job.run()

    def _work(self) -> None:
        now = datetime.now()
        jobs = self.config.get("JOBS", {})
        for job_name, spec in jobs.items():
            schedule = spec.get("SCHEDULE")
            job_class_name = spec.get("JOB_CLASS")
            if not schedule or not job_class_name:
                continue
            if not croniter.is_valid(schedule):
                logger.warning(f"W_Cron: skipping '{job_name}' — invalid schedule {schedule!r}")
                continue
            entry = get_or_create_job(f"{job_class_name}/{job_name}")
            entry.next_run_at = croniter(schedule, now).get_next(datetime).timestamp()
            if croniter(schedule, self._last_check).get_next(datetime) <= now:
                logger.debug(f"W_Cron: firing '{job_name}' ({job_class_name})")
                self._spawn_job(job_name, job_class_name, spec.get("PARAMS") or {}, spec.get("SILENT", False))
        self._last_check = now
        self._update_status(f"Scheduled {len(jobs)} job(s).")
