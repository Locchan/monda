from pathlib import Path

import pytest

from helpers import activate_config, configs_dir, write_config_file
from monda.classes.jobs.hik.J_HikAlertSnap import J_HikAlertSnap


def _load(cfg_path, tmp_path):
    import json

    data = json.loads((configs_dir() / "camera_site.json").read_text(encoding="utf-8"))
    for name, tgt in data["LED_TARGETS"].items():
        p = tmp_path / f"led-{name}"
        p.mkdir(exist_ok=True)
        tgt["BASEDIR"] = str(p)
    # enable alerts for this test
    data["JOB_CONFIG"]["J_HikAlertSnap"] = {"ENABLED": True}
    write_config_file(cfg_path, data)
    activate_config(cfg_path)
    return Path(data["LED_TARGETS"]["camera_alerts"]["BASEDIR"])


def test_initialize_and_work(cfg_path, tmp_path, monkeypatch):
    led = _load(cfg_path, tmp_path)
    j = J_HikAlertSnap("cam4", {
        "HIK_DEVICE": "cam4",
        "MESSAGE": "motion",
    })
    assert j.initialize() is True

    class Resp:
        status_code = 200
        content = b"JPEG"

    monkeypatch.setattr(
        "monda.classes.jobs.hik.J_HikAlertSnap.requests.get",
        lambda *a, **k: Resp(),
    )
    j._work()
    assert list(led.glob("alert_*.json"))


def test_acquire_rate_limit(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    J_HikAlertSnap._last_snap.clear()
    assert J_HikAlertSnap.acquire("cam4") is True
    assert J_HikAlertSnap.acquire("cam4") is False


def test_http_error(cfg_path, tmp_path, monkeypatch):
    _load(cfg_path, tmp_path)
    j = J_HikAlertSnap("cam4", {"HIK_DEVICE": "cam4", "MESSAGE": "x"})
    j.initialize()

    class Resp:
        status_code = 403
        content = b""

    monkeypatch.setattr(
        "monda.classes.jobs.hik.J_HikAlertSnap.requests.get",
        lambda *a, **k: Resp(),
    )
    with pytest.raises(RuntimeError):
        j._work()
