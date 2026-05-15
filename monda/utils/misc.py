import copy
import json
import os
import signal

import yaml
from art import text2art

CONFIG = {}
_config_filepath = None

_dynamic_mtime: float | None = None
_dynamic_config: dict = {}
_merged_config: dict = {}


def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _dynamic_config_path() -> str | None:
    if _config_filepath is None:
        return None
    directory = os.path.dirname(_config_filepath)
    return os.path.join(directory, "dynamic.yaml") if directory else "dynamic.yaml"


def _reload_dynamic() -> dict:
    global _dynamic_mtime, _dynamic_config, _merged_config

    dyn_path = _dynamic_config_path()
    if dyn_path is None or not os.path.exists(dyn_path):
        _dynamic_mtime = None
        _dynamic_config = {}
        _merged_config = copy.deepcopy(CONFIG)
        return _merged_config

    try:
        mtime = os.stat(dyn_path).st_mtime
    except OSError:
        _merged_config = copy.deepcopy(CONFIG)
        return _merged_config

    if mtime == _dynamic_mtime and _merged_config:
        return _merged_config

    _dynamic_mtime = mtime
    try:
        with open(dyn_path, "r", encoding="utf-8") as f:
            _dynamic_config = yaml.safe_load(f) or {}
    except Exception:
        _dynamic_config = {}
        _merged_config = copy.deepcopy(CONFIG)
        return _merged_config

    _merged_config = _deep_merge(copy.deepcopy(CONFIG), _dynamic_config)
    return _merged_config


def read_config(filepath=None, reload=False):
    global CONFIG, _config_filepath, _merged_config

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

    if CONFIG == {} or reload:
        _config_filepath = os.path.abspath(filepath)
        with open(filepath, "r", encoding="utf-8") as config_file:
            try:
                CONFIG = yaml.safe_load(config_file) or {}
                if "DEBUG" in CONFIG and CONFIG["DEBUG"]:
                    print(f"Read config:\n{json.dumps(CONFIG, indent=2)}")
            except Exception as e:
                print(f"Could not read config file {filepath}: {e.__class__.__name__}")
                exit(1)
        _merged_config = {}

    return _reload_dynamic()


def write_config(data, filepath=None):
    if filepath is None:
        if "CFGFILE_PATH" in os.environ:
            filepath = os.environ["CFGFILE_PATH"]
        else:
            filepath = "config.yaml"
    with open(filepath, "w", encoding="utf-8") as config_file:
        yaml.dump(data, config_file, default_flow_style=False, allow_unicode=True)
    read_config(filepath, reload=True)


def write_dynamic_config(path: str, value) -> None:
    dyn_path = _dynamic_config_path()
    if dyn_path is None:
        raise RuntimeError("Static config not loaded yet")

    if os.path.exists(dyn_path):
        with open(dyn_path, "r", encoding="utf-8") as f:
            try:
                data = yaml.safe_load(f) or {}
            except Exception:
                data = {}
    else:
        data = {}

    keys = path.split("/")
    node = data
    for key in keys[:-1]:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    node[keys[-1]] = value

    tmp_path = dyn_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    os.replace(tmp_path, dyn_path)


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
