from pathlib import Path
from types import SimpleNamespace

import pytest

from helpers import activate_config, configs_dir, write_config_file
from monda.classes.jobs.hik.J_HikSnap import J_HikSnap
from monda.utils import status


def _load(cfg_path, tmp_path):
    import json

    data = json.loads((configs_dir() / "camera_site.json").read_text(encoding="utf-8"))
    for name, tgt in data["LED_TARGETS"].items():
        p = tmp_path / f"led-{name}"
        p.mkdir(exist_ok=True)
        tgt["BASEDIR"] = str(p)
    write_config_file(cfg_path, data)
    activate_config(cfg_path)


def test_initialize_ok(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    j = J_HikSnap("snap_cam4", {
        "HIK_DEVICE": "cam4",
        "DEST_DIR": str(tmp_path / "snaps"),
    })
    assert j.initialize() is True


def test_initialize_bad_device(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    j = J_HikSnap("x", {"HIK_DEVICE": "missing", "DEST_DIR": str(tmp_path / "s")})
    assert j.initialize() is False


def test_work_saves_snapshot(cfg_path, tmp_path, monkeypatch):
    _load(cfg_path, tmp_path)
    dest = tmp_path / "snaps"
    j = J_HikSnap("snap_cam4", {"HIK_DEVICE": "cam4", "DEST_DIR": str(dest)})
    assert j.initialize()

    class Resp:
        status_code = 200
        content = b"JPEGDATA"

    monkeypatch.setattr(
        "monda.classes.jobs.hik.J_HikSnap.requests.get",
        lambda *a, **k: Resp(),
    )
    j._work()
    assert any(dest.glob("cam4_*.jpg"))


def test_work_http_failure(cfg_path, tmp_path, monkeypatch):
    _load(cfg_path, tmp_path)
    j = J_HikSnap("snap_cam4", {"HIK_DEVICE": "cam4", "DEST_DIR": str(tmp_path / "s")})
    j.initialize()

    class Resp:
        status_code = 500
        content = b""

    monkeypatch.setattr(
        "monda.classes.jobs.hik.J_HikSnap.requests.get",
        lambda *a, **k: Resp(),
    )
    with pytest.raises(RuntimeError, match="HTTP 500"):
        j._work()
