import json
import os
import sys
from typing import Any

from monda.config_schema import (
    UNSET, Field,
    GLOBAL_FIELDS, LED_TARGET_FIELDS, TELEGRAM_FIELDS,
    HIK_GLOBAL_FIELDS, HIK_DEVICE_FIELDS, HIK_CRED_FIELDS,
    WORKER_SCHEMAS, JOB_SCHEMAS,
)

_OMIT = object()
_PARSE_ERR = object()

def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v)
    return str(v)


def _hr():
    print("─" * 52)


def _header(title: str):
    print()
    _hr()
    print(f"  {title}")
    _hr()

def _parse(ftype: str, raw: str) -> Any:
    if ftype == "int":
        try:
            return int(raw)
        except ValueError:
            print("    ✗ Must be an integer.")
            return _PARSE_ERR
    if ftype == "bool":
        if raw.lower() in ("y", "yes", "true", "1"):
            return True
        if raw.lower() in ("n", "no", "false", "0"):
            return False
        print("    ✗ Enter yes or no.")
        return _PARSE_ERR
    if ftype == "list_str":
        return [x.strip() for x in raw.split(",") if x.strip()]
    if ftype == "list_int":
        try:
            return [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            print("    ✗ Must be comma-separated integers.")
            return _PARSE_ERR
    if ftype == "json":
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"    ✗ Invalid JSON: {e}")
            return _PARSE_ERR
    return raw


def _prompt(field: Field, current: Any = UNSET) -> Any:
    shown = current if current is not UNSET else field.default

    label = f"  {field.key}"
    if shown is not UNSET:
        label += f" [{_fmt(shown)}]"
    if field.optional:
        label += " (optional)"
    label += ": "

    while True:
        try:
            raw = input(label).strip()
        except EOFError:
            return shown if shown is not UNSET else _OMIT

        if not raw:
            if field.optional:
                return _OMIT
            if shown is not UNSET:
                return shown
            print(f"    ✗ {field.key} is required.")
            continue

        result = _parse(field.type, raw)
        if result is _PARSE_ERR:
            continue
        return result


def _configure_fields(data: dict, fields: list[Field]) -> None:
    for field in fields:
        if field.type == "named_list":
            _configure_named_list(data, field.key, field.desc, field.sub_fields)
            continue
        val = _prompt(field, data.get(field.key, UNSET))
        if val is _OMIT:
            data.pop(field.key, None)
        else:
            data[field.key] = val


def _configure_named_list(data: dict, key: str, label: str, sub_fields: list[Field]) -> None:
    entries: dict = data.setdefault(key, {})
    while True:
        _header(f"Manage {label}")
        names = list(entries.keys())
        if names:
            for i, n in enumerate(names, 1):
                print(f"  {i}. {n}")
        else:
            print("  (none)")
        print()
        print("  a. Add entry")
        if names:
            print("  d. Delete entry")
        print("  b. Back")
        raw = input("\nChoice: ").strip().lower()

        if raw == "b":
            break
        if raw == "a":
            name = input("  Entry name: ").strip()
            if not name:
                continue
            entry: dict = entries.setdefault(name, {})
            _header(f"{label} / {name}")
            _configure_fields(entry, sub_fields)
        elif raw == "d" and names:
            name = input("  Delete entry name: ").strip()
            if name in entries:
                del entries[name]
                print(f"  Deleted '{name}'.")
        else:
            try:
                idx = int(raw) - 1
                if 0 <= idx < len(names):
                    name = names[idx]
                    _header(f"{label} / {name}")
                    _configure_fields(entries[name], sub_fields)
            except ValueError:
                pass

    if not entries:
        data.pop(key, None)


def _menu(title: str, options: list[str]) -> int:
    """Returns 0-based index of chosen option, or len(options) for back."""
    while True:
        _header(title)
        for i, opt in enumerate(options, 1):
            print(f"  {i}. {opt}")
        print("  b. Back")
        raw = input("\nChoice: ").strip().lower()
        if raw == "b":
            return len(options)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return idx
        except ValueError:
            pass


def _configure_general(config: dict) -> None:
    _header("General Settings")
    _configure_fields(config, GLOBAL_FIELDS)


def _configure_led_targets(config: dict) -> None:
    targets: dict = config.setdefault("LED_TARGETS", {})
    _configure_named_list(config, "LED_TARGETS", "LED Targets", LED_TARGET_FIELDS)


def _configure_telegram(config: dict) -> None:
    _header("Telegram")
    tg: dict = config.setdefault("TELEGRAM", {})
    _configure_fields(tg, TELEGRAM_FIELDS)
    if not tg:
        config.pop("TELEGRAM", None)


def _configure_hik(config: dict) -> None:
    while True:
        choice = _menu("Hikvision (HIK_CONFIG)", [
            "Global settings",
            "Devices",
            "Credentials",
        ])
        if choice == 3:
            break
        hik: dict = config.setdefault("HIK_CONFIG", {})
        if choice == 0:
            _header("HIK_CONFIG — Global")
            _configure_fields(hik, HIK_GLOBAL_FIELDS)
        elif choice == 1:
            _configure_named_list(hik, "DEVICES", "Devices", HIK_DEVICE_FIELDS)
        elif choice == 2:
            _configure_named_list(hik, "CREDENTIALS", "Credentials", HIK_CRED_FIELDS)
        if not hik:
            config.pop("HIK_CONFIG", None)


def _configure_worker_instance(data: dict, wtype: str) -> None:
    schema = WORKER_SCHEMAS[wtype]
    _header(f"{wtype}")
    print(f"  {schema.description}")
    print()
    _configure_fields(data, schema.fields)


def _configure_workers(config: dict) -> None:
    wtypes = list(WORKER_SCHEMAS.keys())
    while True:
        choice = _menu("Workers", wtypes)
        if choice == len(wtypes):
            break
        wtype = wtypes[choice]
        worker_cfg: dict = config.setdefault("WORKER_CONFIG", {}).setdefault(wtype, {})

        while True:
            instances = list(worker_cfg.keys())
            opts = instances + ["Add instance"]
            if instances:
                opts.append("Delete instance")
            choice2 = _menu(f"{wtype} — instances", opts)
            if choice2 == len(opts):
                break
            if opts[choice2] == "Add instance":
                name = input("  Instance name: ").strip()
                if not name:
                    continue
                worker_cfg[name] = {}
                _configure_worker_instance(worker_cfg[name], wtype)
            elif opts[choice2] == "Delete instance":
                name = input("  Delete instance name: ").strip()
                if name in worker_cfg:
                    del worker_cfg[name]
                    print(f"  Deleted instance '{name}'.")
            else:
                name = instances[choice2]
                _configure_worker_instance(worker_cfg[name], wtype)

        if not worker_cfg:
            config.get("WORKER_CONFIG", {}).pop(wtype, None)

    if not config.get("WORKER_CONFIG"):
        config.pop("WORKER_CONFIG", None)


def _configure_jobs(config: dict) -> None:
    jtypes = list(JOB_SCHEMAS.keys())
    while True:
        choice = _menu("Jobs", jtypes)
        if choice == len(jtypes):
            break
        jtype = jtypes[choice]
        schema = JOB_SCHEMAS[jtype]
        job_cfg: dict = config.setdefault("JOB_CONFIG", {}).setdefault(jtype, {})

        while True:
            instances = [k for k in job_cfg if k != "ENABLED"]
            opts = instances + ["Add instance", "Toggle ENABLED"]
            if instances:
                opts.append("Delete instance")
            choice2 = _menu(f"{jtype} — {schema.description}", opts)
            if choice2 == len(opts):
                break
            label = opts[choice2]
            if label == "Add instance":
                name = input("  Instance name: ").strip()
                if not name:
                    continue
                job_cfg[name] = {}
                _header(f"{jtype} / {name}")
                _configure_fields(job_cfg[name], schema.fields)
            elif label == "Toggle ENABLED":
                current = job_cfg.get("ENABLED", True)
                job_cfg["ENABLED"] = not current
                print(f"  ENABLED → {job_cfg['ENABLED']}")
            elif label == "Delete instance":
                name = input("  Delete instance name: ").strip()
                if name in job_cfg:
                    del job_cfg[name]
                    print(f"  Deleted instance '{name}'.")
            else:
                name = instances[choice2]
                _header(f"{jtype} / {name}")
                _configure_fields(job_cfg[name], schema.fields)

        if not job_cfg:
            config.get("JOB_CONFIG", {}).pop(jtype, None)

    if not config.get("JOB_CONFIG"):
        config.pop("JOB_CONFIG", None)


def _find_config_path(argv_path: str | None) -> str:
    if argv_path:
        return argv_path
    if "CFG_FILE" in os.environ:
        return os.environ["CFG_FILE"]
    if os.path.isfile("config/config.json"):
        return "config/config.json"
    return "/etc/monda/config.json"


def run_configure(argv_path: str | None = None) -> None:
    path = _find_config_path(argv_path)

    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            config: dict = json.load(f)
        print(f"Loaded: {path}")
    else:
        config = {}
        print(f"New config: {path}")

    sections = ["General", "LED Targets", "Telegram", "Hikvision", "Workers", "Jobs"]
    try:
        while True:
            choice = _menu("MonDa Configuration", sections + ["Save & Exit"])
            if choice == len(sections):  # Save & Exit
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2)
                    f.write("\n")
                print(f"\nSaved to {path}")
                break
            if choice == len(sections) + 1:  # Back from top menu = discard
                print("\nDiscarded.")
                break
            [
                _configure_general,
                _configure_led_targets,
                _configure_telegram,
                _configure_hik,
                _configure_workers,
                _configure_jobs,
            ][choice](config)
    except KeyboardInterrupt:
        print("\n\nAborted — changes not saved.")
        sys.exit(0)
