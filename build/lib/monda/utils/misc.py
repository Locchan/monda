import atexit
import json
import os
import signal
from typing import Any

from art import text2art

_config_file: str | None = None
_config_mtime: float | None = None
_config: dict = {}

_pid_file: str | None = None


def _navigate(data: dict, keys: list[str]) -> dict:
    node = data
    for key in keys:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    return node


def read_config(filepath: str | None = None) -> dict:
    global _config_file, _config_mtime, _config

    if _config_file is None:
        if filepath is None:
            if "CFG_FILE" in os.environ:
                filepath = os.environ["CFG_FILE"]
            elif os.path.isfile("config/config.json"):
                filepath = "config/config.json"
            elif os.path.isfile("/etc/monda/config.json"):
                filepath = "/etc/monda/config.json"
            else:
                filepath = "config/config.json"

        if not os.path.isfile(filepath):
            print("Config file not found. Searched (in order):")
            print("  1. CFG_FILE environment variable")
            print("  2. ./config/config.json")
            print("  3. /etc/monda/config.json")
            print(f"Expected config file at '{filepath}'")
            exit(1)

        _config_file = os.path.abspath(filepath)

    try:
        mtime = os.stat(_config_file).st_mtime
    except OSError:
        return _config

    if mtime == _config_mtime:
        return _config

    is_reload = _config_mtime is not None
    _config_mtime = mtime

    try:
        with open(_config_file, "r", encoding="utf-8") as f:
            _config = json.load(f)
        if _config.get("DEBUG"):
            print(f"Read config:\n{json.dumps(_config, indent=2)}")
    except Exception as e:
        if not _config:
            print(f"Could not read config: {e.__class__.__name__}: {e}")
            exit(1)

    if is_reload:
        from monda.utils.logger import get_logger
        get_logger().info("Config change detected, reloaded.")

    return _config


def write_config(data: dict, filepath: str | None = None) -> None:
    global _config_mtime
    path = filepath or _config_file
    if path is None:
        path = os.environ.get("CFG_FILE", "config/config.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    _config_mtime = None
    read_config()


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def set_config_entry(path: str, value: Any) -> None:
    config = read_config()
    keys = path.split("/")
    parent = _navigate(config, keys[:-1])
    leaf = keys[-1]
    if isinstance(parent.get(leaf), dict) and isinstance(value, dict):
        parent[leaf] = _deep_merge(parent[leaf], value)
    else:
        parent[leaf] = value
    write_config(config)


def append_config_entry(path: str, value: Any) -> None:
    config = read_config()
    keys = path.split("/")
    parent = _navigate(config, keys[:-1])
    leaf = keys[-1]
    existing = parent.get(leaf)
    if existing is None:
        parent[leaf] = [value]
    elif isinstance(existing, list):
        parent[leaf] = existing + [value]
    else:
        raise TypeError(f"Config entry at '{path}' is {type(existing).__name__}, not a list")
    write_config(config)


def acquire_pid_file(path: str) -> None:
    global _pid_file
    if os.path.exists(path):
        try:
            pid = int(open(path).read().strip())
            os.kill(pid, 0)
            print(f"Error: another monda instance is already running (PID {pid}).")
            os._exit(1)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"Error: another monda instance is already running.")
            os._exit(1)
        except ValueError:
            pass
    with open(path, "w") as f:
        f.write(str(os.getpid()))
    _pid_file = path
    atexit.register(release_pid_file)


def release_pid_file() -> None:
    global _pid_file
    if _pid_file:
        try:
            os.remove(_pid_file)
        except OSError:
            pass
        _pid_file = None


def signal_stop(_signo: int, _stack_frame: object) -> None:
    from monda.utils.logger import get_logger
    logger = get_logger()
    logger.info(f"Caught {signal.Signals(_signo).name}. Shutting down...")
    release_pid_file()
    os._exit(0)


def splash() -> None:
    from monda.utils.logger import get_logger
    logger = get_logger()
    splash_text = text2art("MonDa", font="Chunky")
    splash_text = splash_text.strip()
    lines = splash_text.split("\n")
    for aline in lines:
        logger.info(aline)
    logger.info("")
