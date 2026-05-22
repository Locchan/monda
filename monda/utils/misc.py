import configparser
import json
import os
import signal
from typing import Any

from art import text2art

_config_dir: str | None = None
_config_mtimes: tuple | None = None  # ((path, mtime), ...) for every scanned .ini file
_config: dict = {}

# Section-name prefix → top-level dict key (None = root).
_NAMESPACE_MAP: dict[str, str | None] = {
    "general": None,
    "hik": "HIK_CONFIG",
    "redis": "REDIS",
    "led": "LED",
    "telegram": "TELEGRAM",
    "worker": "WORKER_CONFIG",
    "job": "JOB_CONFIG",
}
_REVERSE_NAMESPACE_MAP: dict[str, str] = {
    v: k for k, v in _NAMESPACE_MAP.items() if v is not None
}


def _parse_scalar(s: str):
    if s.lower() == "true":
        return True
    if s.lower() == "false":
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _parse_value(raw: str):
    s = raw.strip()
    if s.startswith("["):
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            pass
    return _parse_scalar(s)


def _navigate(data: dict, keys: list[str]) -> dict:
    node = data
    for key in keys:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    return node


def _ini_to_dict(parser: configparser.RawConfigParser) -> dict:
    result: dict = {}
    for section in parser.sections():
        parts = section.split(".")
        namespace = parts[0]
        rest = parts[1:]
        top_key = _NAMESPACE_MAP.get(namespace, namespace if namespace != "general" else None)
        target = result if top_key is None else _navigate(result, [top_key] + list(rest))
        for key, raw in parser.items(section):
            if "." in key:
                key_parts = key.split(".")
                subtarget = _navigate(target, key_parts[:-1])
                subtarget[key_parts[-1]] = _parse_value(raw)
            else:
                target[key] = _parse_value(raw)
    return result


def _register_sources(data: dict, sources: dict, path: str, name: str) -> None:
    """Recursively record `name` as the source for every scalar leaf in `data`."""
    for key, value in data.items():
        cur = f"{path}.{key}" if path else key
        if isinstance(value, dict):
            _register_sources(value, sources, cur, name)
        else:
            sources[cur] = name


def _merge_into(base: dict, sources: dict, new: dict, name: str, path: str = "") -> None:
    """Merge `new` into `base` in-place. `sources` tracks which file set each scalar leaf."""
    for key, value in new.items():
        cur = f"{path}.{key}" if path else key
        if key not in base:
            base[key] = value
            if isinstance(value, dict):
                _register_sources(value, sources, cur, name)
            else:
                sources[cur] = name
        elif isinstance(base[key], dict) and isinstance(value, dict):
            _merge_into(base[key], sources, value, name, cur)
        else:
            raise ValueError(
                f"Config collision at '{cur}': "
                f"'{sources.get(cur, '?')}' and '{name}' both define it"
            )


def _collect_ini_files(directory: str) -> list[str]:
    files = []
    for root, dirs, fnames in os.walk(directory):
        dirs.sort()
        for fname in sorted(fnames):
            if fname.endswith(".ini"):
                files.append(os.path.join(root, fname))
    return files


def _serialize_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, list):
        return json.dumps(v)
    return str(v)


def _collect_sections(data: dict, path: list) -> list:
    """Returns [(section_name, [(key, value), ...]), ...] depth-first."""
    scalars = []
    results = []
    for k, v in data.items():
        if isinstance(v, dict):
            results.extend(_collect_sections(v, path + [k]))
        else:
            scalars.append((k, v))
    if scalars:
        results.insert(0, (".".join(path) if path else "general", scalars))
    return results


def _dict_to_ini(data: dict) -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser()
    parser.optionxform = str  # preserve key case
    general_scalars = [(k, v) for k, v in data.items() if not isinstance(v, dict)]
    if general_scalars:
        parser.add_section("general")
        for k, v in general_scalars:
            parser.set("general", k, _serialize_value(v))
    for top_key, namespace in _REVERSE_NAMESPACE_MAP.items():
        if top_key in data and isinstance(data[top_key], dict):
            for section_name, items in _collect_sections(data[top_key], [namespace]):
                parser.add_section(section_name)
                for k, v in items:
                    parser.set(section_name, k, _serialize_value(v))
    return parser


def read_config(dirpath: str | None = None) -> dict:
    global _config_dir, _config_mtimes, _config

    if _config_dir is None:
        if dirpath is None:
            if "CFG_DIR" in os.environ:
                dirpath = os.environ["CFG_DIR"]
            elif os.path.isdir("config"):
                dirpath = "config"
            elif os.path.isdir("/etc/monda/config"):
                dirpath = "/etc/monda/config"
            else:
                dirpath = "config"

        if not os.path.isdir(dirpath):
            print("Config directory not found. Searched (in order):")
            print("  1. CFG_DIR environment variable")
            print("  2. ./config/")
            print("  3. /etc/monda/config")
            print(f"Expected config directory at '{dirpath}'")
            exit(1)

        _config_dir = os.path.abspath(dirpath)

    try:
        ini_files = _collect_ini_files(_config_dir)
        mtimes = tuple((f, os.stat(f).st_mtime) for f in ini_files)
    except OSError:
        return _config

    if mtimes == _config_mtimes:
        return _config

    is_reload = _config_mtimes is not None
    _config_mtimes = mtimes

    try:
        merged: dict = {}
        sources: dict = {}  # flat dot-path → filename for each scalar leaf
        for ini_path in ini_files:
            parser = configparser.RawConfigParser()
            parser.optionxform = str
            with open(ini_path, "r", encoding="utf-8") as f:
                parser.read_file(f)
            file_dict = _ini_to_dict(parser)
            rel = os.path.relpath(ini_path, _config_dir)
            _merge_into(merged, sources, file_dict, rel)
        _config = merged
        if _config.get("DEBUG"):
            print(f"Read config:\n{json.dumps(_config, indent=2)}")
    except ValueError as e:
        print(f"Config error: {e}")
        exit(1)
    except Exception as e:
        if not _config:
            print(f"Could not read config: {e.__class__.__name__}: {e}")
            exit(1)

    if is_reload:
        from monda.utils.logger import get_logger
        get_logger().info("Config change detected, reloaded.")

    return _config


def write_config(data: dict, filepath: str | None = None) -> None:
    global _config_mtimes
    if filepath is None:
        if _config_dir is not None:
            filepath = os.path.join(_config_dir, "runtime.ini")
        elif "CFG_DIR" in os.environ:
            filepath = os.path.join(os.environ["CFG_DIR"], "runtime.ini")
        else:
            filepath = os.path.join("config", "runtime.ini")
    tmp_path = filepath + ".tmp"
    parser = _dict_to_ini(data)
    with open(tmp_path, "w", encoding="utf-8") as f:
        parser.write(f)
    os.replace(tmp_path, filepath)
    _config_mtimes = None
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
        existing.append(value)
    else:
        raise TypeError(f"Config entry at '{path}' is {type(existing).__name__}, not a list")
    write_config(config)


def signal_stop(_signo: int, _stack_frame: object) -> None:
    from monda.utils.logger import get_logger
    logger = get_logger()
    logger.info(f"Caught {signal.Signals(_signo).name}. Shutting down...")
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
