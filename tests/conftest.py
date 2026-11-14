"""Pytest bootstrap: install a temp CFG_FILE before monda modules are imported."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Must run at import time: monda.classes.workers reads config on import.
# ---------------------------------------------------------------------------
_BOOT_DIR = Path(tempfile.mkdtemp(prefix="monda-test-boot-"))
_BOOT_LED = _BOOT_DIR / "led"
_BOOT_LED.mkdir()
_BOOT_CFG = _BOOT_DIR / "config.json"
_BOOT_CFG.write_text(
    json.dumps(
        {
            "NAME": "monda-test-boot",
            "DEBUG": False,
            "TZ": "UTC",
            "LED_TARGETS": {"general": {"BASEDIR": str(_BOOT_LED)}},
            "WORKER_CONFIG": {},
            "JOB_CONFIG": {},
            "HIK_CONFIG": {"EVENT_DEQUE_MAX_SIZE": 30},
        }
    )
    + "\n",
    encoding="utf-8",
)
os.environ["CFG_FILE"] = str(_BOOT_CFG)


from helpers import (  # noqa: E402
    activate_config,
    make_base_config,
    reset_monda_singletons,
    samples_dir,
    write_config_file,
)

# Clear any config cached during helpers import side-effects
reset_monda_singletons()
os.environ["CFG_FILE"] = str(_BOOT_CFG)


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every test gets a fresh config file and cleared singletons."""
    cfg_path = tmp_path / "config.json"
    led = tmp_path / "led"
    led.mkdir()
    data = make_base_config(LED_TARGETS={"general": {"BASEDIR": str(led)}})
    write_config_file(cfg_path, data)
    monkeypatch.setenv("CFG_FILE", str(cfg_path))
    activate_config(cfg_path)
    yield cfg_path
    reset_monda_singletons()


@pytest.fixture
def cfg_path(_isolated_config: Path) -> Path:
    return _isolated_config


@pytest.fixture
def led_dir(cfg_path: Path) -> Path:
    from monda.utils.misc import read_config

    basedir = Path(read_config()["LED_TARGETS"]["general"]["BASEDIR"])
    basedir.mkdir(parents=True, exist_ok=True)
    return basedir


@pytest.fixture
def sample_text():
    def _load(name: str) -> str:
        return (samples_dir() / name).read_text(encoding="utf-8")

    return _load


@pytest.fixture
def rewrite_config(cfg_path: Path):
    def _rewrite(data: dict) -> dict:
        write_config_file(cfg_path, data)
        return activate_config(cfg_path)

    return _rewrite


@pytest.fixture
def merge_worker(cfg_path: Path):
    def _merge(worker_class: str, instance: str, slice_cfg: dict) -> dict:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        data.setdefault("WORKER_CONFIG", {}).setdefault(worker_class, {})[instance] = slice_cfg
        write_config_file(cfg_path, data)
        return activate_config(cfg_path)

    return _merge


@pytest.fixture
def live_merge_worker(cfg_path: Path):
    """Update worker config on disk without clearing status / reload marks."""
    from helpers import live_update_worker_slice

    def _merge(worker_class: str, instance: str, slice_cfg: dict) -> dict:
        return live_update_worker_slice(cfg_path, worker_class, instance, slice_cfg)

    return _merge


@pytest.fixture
def merge_job(cfg_path: Path):
    def _merge(job_class: str, payload: dict) -> dict:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        data.setdefault("JOB_CONFIG", {})[job_class] = payload
        write_config_file(cfg_path, data)
        return activate_config(cfg_path)

    return _merge


@pytest.fixture
def load_named_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def _load(fixture_name: str) -> Path:
        from helpers import configs_dir

        src = configs_dir() / fixture_name
        dest = tmp_path / fixture_name
        data = json.loads(src.read_text(encoding="utf-8"))
        for name, tgt in data.get("LED_TARGETS", {}).items():
            p = tmp_path / f"led-{name}"
            p.mkdir(exist_ok=True)
            tgt["BASEDIR"] = str(p)
        for _wt, insts in data.get("WORKER_CONFIG", {}).items():
            for _iname, icfg in insts.items():
                if "LOG_PATH" in icfg:
                    log = tmp_path / "auth.log"
                    log.write_text("", encoding="utf-8")
                    icfg["LOG_PATH"] = str(log)
                if "BACKUPS" in icfg:
                    for bname, bcfg in icfg["BACKUPS"].items():
                        if "PATH" in bcfg:
                            p = tmp_path / "backups" / bname
                            p.mkdir(parents=True, exist_ok=True)
                            bcfg["PATH"] = str(p)
        write_config_file(dest, data)
        monkeypatch.setenv("CFG_FILE", str(dest))
        activate_config(dest)
        return dest

    return _load
