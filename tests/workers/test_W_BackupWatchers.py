import json
import sys
import time
from types import SimpleNamespace

from monda.classes.workers.W_BackupWatcherBorg import W_BackupWatcherBorg
from monda.classes.workers.W_BackupWatcherRaw import W_BackupWatcherRaw
from monda.utils import status

borg_mod = sys.modules[W_BackupWatcherBorg.__module__]


def test_raw_backup_on_time(tmp_path, merge_worker):
    bdir = tmp_path / "bk"
    bdir.mkdir()
    (bdir / "f.bin").write_bytes(b"x")
    merge_worker(
        "W_BackupWatcherRaw",
        "main",
        {
            "INTERVAL": 3600,
            "BACKUPS": {
                "cam4": {
                    "PATH": str(bdir),
                    "EXPECTED_PERIOD_MINUTES": 1440,
                    "PERMITTED_LAG_MINUTES": 60,
                }
            },
        },
    )
    w = W_BackupWatcherRaw("main", 3600)
    assert w.initialize()
    w._work()
    assert status.snapshot()["workers"]["W:BkpRaw_main"]["detail"] == "All backups on time."


def test_raw_backup_overdue(tmp_path, merge_worker, led_dir):
    bdir = tmp_path / "bk"
    bdir.mkdir()
    f = bdir / "old.bin"
    f.write_bytes(b"x")
    old = time.time() - 10_000_000
    import os
    os.utime(f, (old, old))
    merge_worker(
        "W_BackupWatcherRaw",
        "main",
        {
            "INTERVAL": 3600,
            "ALERT_TARGET": "general",
            "BACKUPS": {
                "cam4": {
                    "PATH": str(bdir),
                    "EXPECTED_PERIOD_MINUTES": 1,
                    "PERMITTED_LAG_MINUTES": 1,
                }
            },
        },
    )
    w = W_BackupWatcherRaw("main", 3600)
    w.initialize()
    w._work()
    snap = status.snapshot()["workers"]["W:BkpRaw_main"]
    assert snap["color"] == "yellow"
    assert "Overdue" in snap["detail"]
    assert list(led_dir.glob("alert_*.json"))


def test_raw_backup_empty_dict_fails_init(merge_worker):
    merge_worker("W_BackupWatcherRaw", "main", {"INTERVAL": 10, "BACKUPS": {}})
    w = W_BackupWatcherRaw("main", 10)
    assert w.initialize() is False


def test_borg_backup_ok(tmp_path, merge_worker, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    merge_worker(
        "W_BackupWatcherBorg",
        "main",
        {
            "INTERVAL": 3600,
            "BACKUPS": {
                "host_alpha": {
                    "PATH": str(repo),
                    "EXPECTED_PERIOD_MINUTES": 1440,
                    "PERMITTED_LAG_MINUTES": 60,
                }
            },
        },
    )
    payload = {"archives": [{"start": time.strftime("%Y-%m-%dT%H:%M:%S")}]}
    monkeypatch.setattr(
        borg_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr=""),
    )
    w = W_BackupWatcherBorg("main", 3600)
    assert w.initialize()
    w._work()
    assert status.snapshot()["workers"]["W:BkpBorg_main"]["detail"] == "All backups on time."


def test_borg_list_failure_alerts(tmp_path, merge_worker, monkeypatch, led_dir):
    repo = tmp_path / "repo"
    repo.mkdir()
    merge_worker(
        "W_BackupWatcherBorg",
        "main",
        {
            "INTERVAL": 3600,
            "ALERT_TARGET": "general",
            "BACKUPS": {
                "host_alpha": {
                    "PATH": str(repo),
                    "EXPECTED_PERIOD_MINUTES": 1440,
                    "PERMITTED_LAG_MINUTES": 60,
                }
            },
        },
    )
    monkeypatch.setattr(
        borg_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="lock"),
    )
    w = W_BackupWatcherBorg("main", 3600)
    w.initialize()
    w._work()
    assert list(led_dir.glob("alert_*.json"))
