from types import SimpleNamespace
import sys

from monda.classes.workers.W_SystemdWatcher import W_SystemdWatcher
from monda.utils import status

systemd_mod = sys.modules[W_SystemdWatcher.__module__]


def test_no_failures(merge_worker, monkeypatch):
    merge_worker("W_SystemdWatcher", "main", {"INTERVAL": 60})
    monkeypatch.setattr(systemd_mod.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="", stderr=""))
    w = W_SystemdWatcher("main", 60)
    assert w.initialize()
    w._work()
    assert status.snapshot()["workers"]["W:Systemd_main"]["detail"] == "No failures detected."


def test_failed_service_alerts(merge_worker, monkeypatch, led_dir):
    merge_worker("W_SystemdWatcher", "main", {"INTERVAL": 60, "ALERT_TARGET": "general"})
    monkeypatch.setattr(
        systemd_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="foo.service loaded failed failed\n", stderr=""),
    )
    w = W_SystemdWatcher("main", 60)
    w.initialize()
    w._work()
    snap = status.snapshot()["workers"]["W:Systemd_main"]
    assert "foo.service" in snap["detail"]
    assert snap["color"] == "yellow"
    assert list(led_dir.glob("alert_*.json"))


def test_ignore_service(merge_worker, monkeypatch, led_dir):
    merge_worker("W_SystemdWatcher", "main", {"INTERVAL": 60, "IGNORE": ["foo.service"]})
    monkeypatch.setattr(
        systemd_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout="foo.service loaded failed failed\n", stderr=""),
    )
    w = W_SystemdWatcher("main", 60)
    w.initialize()
    w._work()
    assert status.snapshot()["workers"]["W:Systemd_main"]["detail"] == "No failures detected."


def test_systemctl_error_logged(merge_worker, monkeypatch):
    merge_worker("W_SystemdWatcher", "main", {"INTERVAL": 60})
    monkeypatch.setattr(
        systemd_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )
    w = W_SystemdWatcher("main", 60)
    w.initialize()
    w._work()
