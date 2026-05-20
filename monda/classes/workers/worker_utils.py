from threading import Thread

from monda.classes.workers import ENABLED_WORKERS
from monda.utils.logger import get_logger
from monda.utils.misc import read_config

logger = get_logger()

def start_worker_by_name(worker_type: str, instance_name: str) -> Thread | None:
    worker_config = read_config().get("WORKER_CONFIG", {})
    instances = worker_config.get(worker_type, {})
    if instance_name not in instances:
        return None
    interval = instances[instance_name].get("INTERVAL", 10)
    worker = ENABLED_WORKERS[worker_type](instance_name, interval)
    if not worker.initialize():
        return None
    return worker.run()

def validate_worker_config():
    worker_config = read_config().get("WORKER_CONFIG", {})
    for worker_type, instances in worker_config.items():
        seen = []
        for name in instances:
            if name in seen:
                logger.error(f"Duplicate instance name '{name}' within worker type '{worker_type}'")
                return False
            seen.append(name)
    return True

def start_all_workers() -> list[tuple]:
    logger.info("Starting all workers...")
    worker_config = read_config().get("WORKER_CONFIG", {})
    threads = []
    for worker_type, instances in worker_config.items():
        for instance_name in instances:
            thread = start_worker_by_name(worker_type, instance_name)
            if thread is not None:
                threads.append((thread, worker_type, instance_name))
    return threads