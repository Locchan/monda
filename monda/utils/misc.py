import json
import os
import signal

import yaml
from art import text2art

_config_filepath: str | None = None
_config_mtime: float | None = None
_config: dict = {}


def read_config(filepath=None):
    global _config_filepath, _config_mtime, _config

    if _config_filepath is None:
        if filepath is None:
            if "CFGFILE_PATH" in os.environ:
                filepath = os.environ["CFGFILE_PATH"]
            elif os.path.exists("config.yaml"):
                filepath = "config.yaml"
            elif os.path.exists("/etc/monda/config.yaml"):
                filepath = "/etc/monda/config.yaml"
            else:
                filepath = "config.yaml"

        if not os.path.exists(filepath):
            print("Config file not found. Searched (in order):")
            print("  1. CFGFILE_PATH environment variable")
            print("  2. ./config.yaml")
            print("  3. /etc/monda/config.yaml")
            print(f"Expected to find the config file at '{filepath}'")
            exit(1)

        _config_filepath = os.path.abspath(filepath)

    try:
        mtime = os.stat(_config_filepath).st_mtime
    except OSError:
        return _config

    if mtime == _config_mtime:
        return _config

    _config_mtime = mtime
    try:
        with open(_config_filepath, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
            if _config.get("DEBUG"):
                print(f"Read config:\n{json.dumps(_config, indent=2)}")
    except Exception as e:
        if not _config:
            print(f"Could not read config file {_config_filepath}: {e.__class__.__name__}")
            exit(1)

    return _config


def write_config(data, filepath=None):
    global _config_mtime
    path = filepath or _config_filepath
    if path is None:
        if "CFGFILE_PATH" in os.environ:
            path = os.environ["CFGFILE_PATH"]
        else:
            path = "config.yaml"
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    os.replace(tmp_path, path)
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


def _navigate(data: dict, keys: list[str]) -> dict:
    node = data
    for key in keys:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    return node


def set_config_entry(path: str, value) -> None:
    config = read_config()
    keys = path.split("/")
    parent = _navigate(config, keys[:-1])
    leaf = keys[-1]
    if isinstance(parent.get(leaf), dict) and isinstance(value, dict):
        parent[leaf] = _deep_merge(parent[leaf], value)
    else:
        parent[leaf] = value
    write_config(config)


def append_config_entry(path: str, value) -> None:
    config = read_config()
    keys = path.split("/")
    parent = _navigate(config, keys[:-1])
    leaf = keys[-1]
    existing = parent.get(leaf)
    if existing is None:
        parent[leaf] = [value]
    elif isinstance(existing, list):
        existing.append(value)
    else:
        raise TypeError(f"Config entry at '{path}' is {type(existing).__name__}, not a list")
    write_config(config)


def signal_stop(_signo, _stack_frame):
    from monda.utils.logger import get_logger
    logger = get_logger()
    logger.info(f"Caught {signal.Signals(_signo).name}. Shutting down...")
    os._exit(0)


def splash():
    from monda.utils.logger import get_logger
    logger = get_logger()
    splash_text = text2art("MonDa", font="Chunky")
    splash_text = splash_text.strip()
    lines = splash_text.split("\n")
    for aline in lines:
        logger.info(aline)
    logger.info("")
