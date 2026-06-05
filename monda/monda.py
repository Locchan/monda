#!/usr/bin/env python3

import json
import os
import signal
import sys
import time
import urllib.request
import urllib.error

from monda.classes.workers.W_ConfigWatch import W_ConfigWatch
from monda.classes.workers.worker_utils import validate_worker_config, start_worker_by_name, start_all_workers
from monda.configure import run_configure
from monda.utils.fmt import format_status_text
from monda.utils.logger import get_logger, resolve_log_dir, setdebug, setup_log_dir
from monda.utils.logs_cmd import run_logs
from monda.utils.misc import splash, read_config, signal_stop, acquire_pid_file


_DEFAULT_PID_FILE = "/tmp/monda.pid"


def _start_config_watcher() -> None:
    config = read_config()
    interval = config.get("CONFIG_WATCH_INTERVAL", 5)
    watcher = W_ConfigWatch("config_watch", interval)
    watcher.config = {}
    watcher.initialized = True
    watcher.run()


def _cmd_status() -> None:
    config = read_config()
    instances = config.get("WORKER_CONFIG", {}).get("W_MondaStatus", {})
    if not instances:
        print("W_MondaStatus is not configured.")
        sys.exit(1)
    port = next(iter(instances.values())).get("PORT", 7342)
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/status", timeout=3) as resp:
            data = json.loads(resp.read())
    except urllib.error.URLError as e:
        print(f"Could not reach monda status at port {port}: {e.reason}")
        sys.exit(1)
    except Exception as e:
        print(f"Could not reach monda status at port {port}: {e}")
        sys.exit(1)

    print(format_status_text(data), end="")


def main() -> None:
    if len(sys.argv) > 1:
        if sys.argv[1] == "status":
            _cmd_status()
            return
        if sys.argv[1] == "configure":
            run_configure(sys.argv[2] if len(sys.argv) > 2 else None)
            return
        if sys.argv[1] == "logs":
            run_logs()
            return
        print(f"Unknown command: {sys.argv[1]}")
        print("Usage: monda [status|configure [config_path]|logs]")
        sys.exit(1)

    signal.signal(signal.SIGTERM, signal_stop)
    signal.signal(signal.SIGINT, signal_stop)

    pid_file = read_config().get("PID_FILE", _DEFAULT_PID_FILE)
    acquire_pid_file(pid_file)

    splash()

    logger = get_logger()
    config = read_config()

    log_dir = resolve_log_dir(config)
    if log_dir:
        setup_log_dir(log_dir)

    if "DEBUG" in config and config["DEBUG"]:
        setdebug()

    _start_config_watcher()

    validate_worker_config()

    worker_threads = start_all_workers()

    if not worker_threads:
        logger.error("FATAL: Could not start workers.")
        os._exit(1)

    while True:
        for i, (thread, worker_type, instance_name) in enumerate(worker_threads):
            if not thread.is_alive():
                logger.warning(f"Resurrecting a dead worker: {thread.name}")
                new_thread = start_worker_by_name(worker_type, instance_name)
                if new_thread is not None:
                    worker_threads[i] = (new_thread, worker_type, instance_name)
                else:
                    logger.error(f"Could not resurrect dead worker: {thread.name}")
            time.sleep(0.5)
        time.sleep(5)


if __name__ == "__main__":
    main()
