from threading import Thread

from monda.classes.workers import ENABLED_WORKERS
from monda.utils.logger import get_logger
from monda.utils.misc import read_config

logger = get_logger()

def start_worker_by_name(name: str) -> Thread | None:
    worker_config = read_config().get("WORKER_CONFIG", {})
    for worker_type, instances in worker_config.items():
        if name in instances:
            interval = instances[name].get("INTERVAL", 10)
            worker = ENABLED_WORKERS[worker_type](name, interval)
            if not worker.initialize():
                return None
            return worker.run()
    return None

def validate_worker_config():
    worker_config = read_config().get("WORKER_CONFIG", {})
    names = []
    for aworker_type in worker_config:
        for aname in worker_config[aworker_type]:
            if aname not in names:
                names.append(aname)
            else:
                logger.error(f"Duplicate names detected: multiple workers named '{aname}'")
                return False
    return True

def start_all_workers() -> list[Thread]:
    logger.info("Starting all workers...")
    worker_config = read_config().get("WORKER_CONFIG", {})
    threads = []
    for instances in worker_config.values():
        for name in instances:
            thread = start_worker_by_name(name)
            if thread is not None:
                threads.append(thread)
    return threads