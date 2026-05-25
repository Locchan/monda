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
from monda.utils.logger import get_logger, setdebug, setup_file_logging
from monda.utils.misc import splash, read_config, signal_stop, acquire_pid_file


_DEFAULT_PID_FILE = "/tmp/monda.pid"


def _start_config_watcher() -> None:
    config = read_config()
    interval = config.get("CONFIG_WATCH_INTERVAL", 5)
    watcher = W_ConfigWatch("config_watch", interval)
    watcher.config = {}
    watcher.initialized = True
    watcher.run()


def _format_uptime(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def _ago(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s ago"
    if s < 3600:
        return f"{s // 60}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def _in_time(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"in {s}s"
    if s < 3600:
        return f"in {s // 60}m"
    if s < 86400:
        return f"in {s // 3600}h"
    return f"in {s // 86400}d"


_COLOR_EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


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

    version = data.get("version", "?")
    uptime = data.get("uptime_seconds")
    uptime_str = _format_uptime(uptime) if uptime is not None else "?"

    all_colors = (
        [w.get("color", "green") for w in data.get("workers", {}).values()]
        + [j.get("color", "green") for j in data.get("jobs", {}).values()]
    )
    if "red" in all_colors:
        overall = "🔴"
    elif "yellow" in all_colors:
        overall = "🟡"
    else:
        overall = "🟢"

    print(f"{overall}  monda v{version} | uptime: {uptime_str}")

    workers = data.get("workers", {})
    if workers:
        print("\nWorkers:")
        for name, w in workers.items():
            emoji = _COLOR_EMOJI.get(w.get("color", "green"), "🟢")
            detail = w.get("detail", "")
            crashed_ago = w.get("crashed_ago")
            restart_count = w.get("restart_count", 0)
            last_restart_ago = w.get("last_restart_ago")
            if crashed_ago is not None:
                crash_error = w.get("crash_error") or "unknown error"
                suffix = f" [Crashed {_ago(crashed_ago)}: {crash_error}]"
            elif last_restart_ago is not None and restart_count > 0:
                suffix = f" [Restarted {_ago(last_restart_ago)}, {restart_count}x]"
            else:
                suffix = ""
            print(f"  {emoji}  {name:<30} {detail}{suffix}")

    jobs = data.get("jobs", {})
    if jobs:
        print("\nJobs:")
        for key, j in jobs.items():
            emoji = _COLOR_EMOJI.get(j.get("color", "green"), "🟢")
            detail = j.get("detail", "")
            next_run_in = j.get("next_run_in")
            parts = [detail]
            if next_run_in is not None:
                parts.append(f"Next: {_in_time(next_run_in)}")
            print(f"  {emoji}  {key:<38} {' | '.join(parts)}")


def main() -> None:
    if len(sys.argv) > 1:
        if sys.argv[1] == "status":
            _cmd_status()
            return
        print(f"Unknown command: {sys.argv[1]}")
        print("Usage: monda [status]")
        sys.exit(1)

    signal.signal(signal.SIGTERM, signal_stop)
    signal.signal(signal.SIGINT, signal_stop)

    pid_file = read_config().get("PID_FILE", _DEFAULT_PID_FILE)
    acquire_pid_file(pid_file)

    splash()

    logger = get_logger()
    config = read_config()

    log_file = config.get("LOG_FILE", {})
    if log_file:
        setup_file_logging(log_file)

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
