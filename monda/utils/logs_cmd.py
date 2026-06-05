import os
import sys

from monda.utils.logger import get_log_dir, list_log_files, resolve_log_dir
from monda.utils.misc import read_config


def _display_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0]


def _select_from_list(paths: list[str]) -> str | None:
    for i, path in enumerate(paths, 1):
        print(f"  {i}. {_display_name(path)}")
    print()
    while True:
        try:
            raw = input("Choice: ").strip()
        except EOFError:
            return None
        if not raw:
            continue
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(paths):
                return paths[idx]
        except ValueError:
            pass
        print(f"  Enter a number from 1 to {len(paths)}.")


def run_logs() -> None:
    config = read_config()
    log_dir = resolve_log_dir(config)

    from monda.utils import logger as logger_mod
    if logger_mod.get_log_dir() is None:
        logger_mod.setup_log_dir(log_dir)

    print()
    print("Select log type:")
    print("  1. general")
    print("  2. worker")
    print("  3. job")
    print()

    try:
        choice = input("Choice: ").strip()
    except EOFError:
        sys.exit(1)

    if choice == "1":
        path = os.path.join(log_dir, "general.log")
    elif choice == "2":
        paths = list_log_files("workers", log_dir)
        if not paths:
            print("No worker log files found.")
            sys.exit(1)
        print()
        path = _select_from_list(paths)
        if path is None:
            sys.exit(1)
    elif choice == "3":
        paths = list_log_files("jobs", log_dir)
        if not paths:
            print("No job log files found.")
            sys.exit(1)
        print()
        path = _select_from_list(paths)
        if path is None:
            sys.exit(1)
    else:
        print("Invalid choice.")
        sys.exit(1)

    if not os.path.isfile(path):
        print(f"Log file does not exist: {path}")
        sys.exit(1)

    os.execvp("less", ["less", path])
