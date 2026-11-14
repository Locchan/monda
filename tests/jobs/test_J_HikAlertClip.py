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

    # Bypass RTSP/ffmpeg entirely: stub the private download helper if present,
    # otherwise stub _work's network side by replacing subprocess and sleeps.
    monkeypatch.setattr(clip_mod.time, "sleep", lambda *_: None)
    monkeypatch.setattr(clip_mod, "_PLAYBACK_LAG", 0.0)
    monkeypatch.setattr(clip_mod, "_DOWNLOAD_ATTEMPTS", 1)
    monkeypatch.setattr(clip_mod, "_MIN_BYTES", 1)
    monkeypatch.setattr(clip_mod, "_RETRY_DELAY_S", 0)

    def fake_run(cmd, **kwargs):
        # Always write a dummy outfile for any ffmpeg invocation.
        out = cmd[-1] if isinstance(cmd, (list, tuple)) else None
        if out and not str(out).startswith("-"):
            Path(out).write_bytes(b"CLIPDATA-MORE-THAN-MIN")
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(clip_mod.subprocess, "run", fake_run)

    # If job uses Popen instead of run, also stub that.
    class FakePopen:
        def __init__(self, *a, **k):
            self.returncode = 0
        def communicate(self, *a, **k):
            return ("", "")
        def wait(self):
            return 0

    monkeypatch.setattr(clip_mod.subprocess, "Popen", FakePopen)

    # Prefer stubbing a high-level method if available
    if hasattr(j, "_download_clip"):
        def fake_dl(*a, **k):
            path = tmp_path / "clip.mp4"
            path.write_bytes(b"CLIPDATA-MORE-THAN-MIN")
            return str(path)
        monkeypatch.setattr(j, "_download_clip", fake_dl)

    j._work()
    assert list(led.glob("alert_*.json"))
