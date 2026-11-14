"""Shared test helpers: config injection, status reset, worker/job factories."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def samples_dir() -> Path:
    return FIXTURES / "samples"


def configs_dir() -> Path:
    return FIXTURES / "configs"


def reset_monda_singletons() -> None:
    """Clear process-wide config cache, status registry, and Job disable list."""
    import monda.utils.misc as misc
    import monda.utils.status as status
    from monda.classes.base.Job import Job

    misc._config_file = None
    misc._config_mtime = None
    misc._config = {}
    status._workers.clear()
    status._jobs.clear()
    status._config_reloads.clear()
    status._pending_sleep_until.clear()
    Job.disabled_jobs.clear()


def write_config_file(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def activate_config(path: Path) -> dict[str, Any]:
    """Point CFG_FILE at path, reset cache, return loaded config."""
    reset_monda_singletons()
    os.environ["CFG_FILE"] = str(path)
    from monda.utils.misc import read_config

    return read_config()


def load_fixture_config(name: str, dest: Path) -> dict[str, Any]:
    src = configs_dir() / name
    data = json.loads(src.read_text(encoding="utf-8"))
    write_config_file(dest, data)
    return activate_config(dest)


def patch_worker_slice(
    cfg_path: Path,
    worker_class: str,
    instance: str,
    slice_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Merge a worker instance into the active config file and reload."""
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data.setdefault("WORKER_CONFIG", {}).setdefault(worker_class, {})[instance] = slice_cfg
    write_config_file(cfg_path, data)
    # bump mtime awareness
    reset_monda_singletons()
    os.environ["CFG_FILE"] = str(cfg_path)
    from monda.utils.misc import read_config

    return read_config()


def live_update_worker_slice(
    cfg_path: Path,
    worker_class: str,
    instance: str,
    slice_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Update a running worker's config on disk without wiping status/reload marks.

    Use this for live-reload tests. Unlike ``activate_config`` / ``patch_worker_slice``,
    it only invalidates the config mtime cache so ``read_config()`` picks up the file.
    """
    import monda.utils.misc as misc

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data.setdefault("WORKER_CONFIG", {}).setdefault(worker_class, {})[instance] = slice_cfg
    write_config_file(cfg_path, data)
    misc._config_mtime = None
    return misc.read_config()


def make_base_config(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "NAME": "monda-test",
        "DEBUG": False,
        "TZ": "UTC",
        "CONFIG_WATCH_INTERVAL": 5,
        "LED_TARGETS": {"general": {"BASEDIR": "/tmp/monda-test-led"}},
        "WORKER_CONFIG": {},
        "JOB_CONFIG": {},
    }
    cfg.update(overrides)
    return cfg
