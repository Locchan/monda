import os
import time

from monda.classes.workers.worker_utils import validate_worker_config, start_worker_by_name, start_all_workers
from monda.utils.logger import get_logger, setdebug

from monda.utils.misc import splash, read_config

splash()

logger = get_logger()
config = read_config()

if "DEBUG" in config and config["DEBUG"]:
    setdebug()

validate_worker_config()

worker_threads = start_all_workers()

if not worker_threads:
    logger.error("FATAL: Could not start workers.")
    os._exit(0)

while True:
    for anindex, athread in enumerate(worker_threads):
        if not athread.is_alive():
            dead_worker_name = athread.name.split("-")[1]
            logger.warning("Resurrecting a dead worker: " + athread.name)
            resurrected_thr = start_worker_by_name(dead_worker_name)
            if resurrected_thr is not None:
                worker_threads[anindex] = resurrected_thr
            else:
                logger.error("Could not resurrect a dead worker: " + dead_worker_name)
        time.sleep(5)
