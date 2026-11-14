import logging
from threading import Thread

from monda.classes.workers import ENABLED_WORKERS
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger
from monda.utils.misc import read_config

logger: logging.Logger = get_logger()


def start_worker_by_name(
    worker_type: str,
    instance_name: str,
    config_reload: bool = False,
) -> Thread | None:
    if worker_type not in ENABLED_WORKERS:
        logger.error(
            f"Unknown worker type '{worker_type}' (not in this MonDa build); "
            f"cannot start '{instance_name}'."
        )
        return None
    worker_config = read_config().get("WORKER_CONFIG", {})
    instances = worker_config.get(worker_type, {})
    if instance_name not in instances:
        return None
    interval = instances[instance_name].get("INTERVAL", 10)
    worker = ENABLED_WORKERS[worker_type](instance_name, interval)
    if not worker.initialize(config_reload=config_reload):
        return None
    return worker.run()


def validate_worker_config() -> bool:
    worker_config = read_config().get("WORKER_CONFIG", {})
    ok = True
    for worker_type, instances in worker_config.items():
        if worker_type not in ENABLED_WORKERS:
            logger.error(
                f"Unknown worker type '{worker_type}' in WORKER_CONFIG "
                f"(not in this MonDa build)."
            )
            ok = False
            continue
        if not isinstance(instances, dict):
            logger.error(f"WORKER_CONFIG.{worker_type} must be an object of instances.")
            return False
        seen = []
        for name in instances:
            if name in seen:
                logger.error(
                    f"Duplicate instance name '{name}' within worker type '{worker_type}'"
                )
                return False
            seen.append(name)
    return ok


def start_all_workers() -> list[tuple[Thread | None, str, str]]:
    logger.info("Starting all workers...")
    worker_config = read_config().get("WORKER_CONFIG", {})
    threads = []
    for worker_type, instances in worker_config.items():
        if worker_type not in ENABLED_WORKERS:
            # Skip — do not put unknown types on the supervisor list.
            count = len(instances) if isinstance(instances, dict) else 0
            msg = (
                f"Misconfiguration: unknown worker type '{worker_type}' "
                f"({count} instance(s)) is not in this MonDa build; skipped."
            )
            logger.error(msg)
            send_alert(msg, target="general")
            continue
        for instance_name in instances:
            thread = start_worker_by_name(worker_type, instance_name)
            # Keep failed initializations in the supervisor list so the main
            # loop can retry them later.
            threads.append((thread, worker_type, instance_name))
    return threads
