from types import SimpleNamespace
import sys

from monda.classes.workers.W_ZFSWatcher import W_ZFSWatcher
from monda.utils import status

zfs_mod = sys.modules[W_ZFSWatcher.__module__]


def _worker(merge_worker, monkeypatch, sample: str, which=True):
    merge_worker("W_ZFSWatcher", "main", {"INTERVAL": 30, "ALERT_TARGET": "general"})
    monkeypatch.setattr(zfs_mod.shutil, "which", lambda _: "/usr/sbin/zpool" if which else None)
    monkeypatch.setattr(
        zfs_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=sample, stderr=""),
    )
    return W_ZFSWatcher("main", 30)


def test_initialize_requires_zpool(merge_worker, monkeypatch):
    merge_worker("W_ZFSWatcher", "main", {"INTERVAL": 30})
    monkeypatch.setattr(zfs_mod.shutil, "which", lambda _: None)
    w = W_ZFSWatcher("main", 30)
    assert w.initialize() is False


def test_healthy_pools(sample_text, merge_worker, monkeypatch):
    w = _worker(merge_worker, monkeypatch, sample_text("zpool_healthy.txt"))
    assert w.initialize() is True
    w._work()
    snap = status.snapshot()["workers"]["W:ZFS_main"]
    assert snap["detail"] == "1/1 pools healthy."
    assert snap["color"] == "green"


def test_degraded_pools_red_alert(sample_text, merge_worker, monkeypatch, led_dir):
    w = _worker(merge_worker, monkeypatch, sample_text("zpool_degraded.txt"))
    assert w.initialize() is True
    w._prev_scan = {"zraid1": "scrub"}
    w._work()
    snap = status.snapshot()["workers"]["W:ZFS_main"]
    assert snap["detail"] == "0/1 pools healthy."
    assert snap["color"] == "red"
    assert list(led_dir.glob("alert_*.json"))


def test_no_pools_available(merge_worker, monkeypatch):
    merge_worker("W_ZFSWatcher", "main", {"INTERVAL": 30})
    monkeypatch.setattr(zfs_mod.shutil, "which", lambda _: "/usr/sbin/zpool")
    monkeypatch.setattr(
        zfs_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="no pools available"),
    )
    w = W_ZFSWatcher("main", 30)
    assert w.initialize() is True
    w._work()
    assert status.snapshot()["workers"]["W:ZFS_main"]["detail"] == "0/0 pools healthy."


def test_ignore_pool(sample_text, merge_worker, monkeypatch, led_dir):
    merge_worker("W_ZFSWatcher", "main", {"INTERVAL": 30, "IGNORE": ["zraid1"]})
    monkeypatch.setattr(zfs_mod.shutil, "which", lambda _: "/sbin/zpool")
    monkeypatch.setattr(
        zfs_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=sample_text("zpool_degraded.txt"), stderr=""),
    )
    w = W_ZFSWatcher("main", 30)
    assert w.initialize() is True
    w._work()
    snap = status.snapshot()["workers"]["W:ZFS_main"]
    assert snap["detail"] == "0/0 pools healthy."
    assert snap["color"] == "green"
