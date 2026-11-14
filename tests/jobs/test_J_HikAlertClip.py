from datetime import datetime
from pathlib import Path
import sys

from helpers import activate_config, configs_dir, write_config_file
from monda.classes.jobs.hik.J_HikAlertClip import J_HikAlertClip

clip_mod = sys.modules[J_HikAlertClip.__module__]


def _load(cfg_path, tmp_path):
    import json

    data = json.loads((configs_dir() / "camera_site.json").read_text(encoding="utf-8"))
    for name, tgt in data["LED_TARGETS"].items():
        p = tmp_path / f"led-{name}"
        p.mkdir(exist_ok=True)
        tgt["BASEDIR"] = str(p)
    data["JOB_CONFIG"]["J_HikAlertClip"] = {"ENABLED": True}
    write_config_file(cfg_path, data)
    activate_config(cfg_path)
    return Path(data["LED_TARGETS"]["camera_alerts"]["BASEDIR"])


def test_initialize_ok(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    j = J_HikAlertClip("cam4", {
        "HIK_DEVICE": "cam4",
        "MESSAGE": "clip",
        "ALERT_TIME": datetime.now().isoformat(),
        "BEFORE_SEC": 1,
        "AFTER_SEC": 1,
    })
    assert j.initialize() is True


def test_initialize_missing_device(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    j = J_HikAlertClip("x", {
        "HIK_DEVICE": "missing",
        "MESSAGE": "clip",
        "ALERT_TIME": datetime.now().isoformat(),
    })
    assert j.initialize() is False


def test_acquire_rate_limit(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    J_HikAlertClip._last_clip.clear()
    assert J_HikAlertClip.acquire("cam4") is True
    assert J_HikAlertClip.acquire("cam4") is False


def _stub_download(j, tmp_path, monkeypatch, payload=b"CLIPDATA-MORE-THAN-MIN"):
    import tempfile
    import time

    monkeypatch.setattr(clip_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(clip_mod, "_PLAYBACK_LAG", 0.0)

    def fake_dl(*a, **k):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        path = Path(tempfile.gettempdir()) / f"{stamp}_cam4.mp4"
        path.write_bytes(payload)
        return str(path)

    monkeypatch.setattr(j, "_download_clip", fake_dl)


def test_work_with_mocked_download(cfg_path, tmp_path, monkeypatch):
    led = _load(cfg_path, tmp_path)
    j = J_HikAlertClip("cam4", {
        "HIK_DEVICE": "cam4",
        "MESSAGE": "clip",
        "ALERT_TIME": datetime.now().isoformat(),
        "BEFORE_SEC": 1,
        "AFTER_SEC": 1,
    })
    assert j.initialize()
    _stub_download(j, tmp_path, monkeypatch)
    j._work()
    assert list(led.glob("alert_*.json"))


def test_store_mode_writes_under_job_class_instance(cfg_path, tmp_path, monkeypatch):
    led = _load(cfg_path, tmp_path)
    store = tmp_path / "store"
    j = J_HikAlertClip("cam_1", {
        "HIK_DEVICE": "cam4",
        "MODE": "STORE",
        "STOREDIR": str(store),
        "ALERT_TIME": datetime.now().isoformat(),
        "BEFORE_SEC": 1,
        "AFTER_SEC": 1,
    })
    assert j.initialize()
    _stub_download(j, tmp_path, monkeypatch, payload=b"CLIPBYTES")
    j._work()
    dest_dir = store / "J_HikAlertClip" / "cam_1"
    files = list(dest_dir.glob("*_cam4.mp4"))
    assert len(files) == 1
    assert files[0].read_bytes() == b"CLIPBYTES"
    assert list(led.glob("alert_*.json")) == []


def test_store_mode_requires_storedir(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    j = J_HikAlertClip("cam_1", {
        "HIK_DEVICE": "cam4",
        "MODE": "STORE",
        "ALERT_TIME": datetime.now().isoformat(),
        "BEFORE_SEC": 1,
        "AFTER_SEC": 1,
    })
    assert j.initialize() is False
