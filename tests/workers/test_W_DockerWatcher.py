import json
import sys
from types import SimpleNamespace

from monda.classes.workers.W_DockerWatcher import W_DockerWatcher
from monda.utils import status

docker_mod = sys.modules[W_DockerWatcher.__module__]


def test_healthy_containers(merge_worker, monkeypatch):
    merge_worker("W_DockerWatcher", "main", {"INTERVAL": 60})
    line = json.dumps({"Names": "immich_server", "State": "running"})

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "ps", "-a"]:
            return SimpleNamespace(returncode=0, stdout=line + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="immich_server\t0\n", stderr="")

    monkeypatch.setattr(docker_mod.subprocess, "run", fake_run)
    w = W_DockerWatcher("main", 60)
    assert w.initialize()
    w._work()
    assert "healthy" in status.snapshot()["workers"]["W:Docker_main"]["detail"]


def test_exited_container_alerts(merge_worker, monkeypatch, led_dir):
    merge_worker("W_DockerWatcher", "main", {"INTERVAL": 60, "ALERT_TARGET": "general"})
    line = json.dumps({"Names": "bad", "State": "exited"})

    def fake_run(cmd, **kwargs):
        if cmd[:3] == ["docker", "ps", "-a"]:
            return SimpleNamespace(returncode=0, stdout=line + "\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="bad\t1\n", stderr="")

    monkeypatch.setattr(docker_mod.subprocess, "run", fake_run)
    w = W_DockerWatcher("main", 60)
    w.initialize()
    w._work()
    snap = status.snapshot()["workers"]["W:Docker_main"]
    assert snap["color"] == "yellow"
    assert list(led_dir.glob("alert_*.json"))


def test_docker_query_failure(merge_worker, monkeypatch):
    merge_worker("W_DockerWatcher", "main", {"INTERVAL": 60})
    monkeypatch.setattr(
        docker_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="denied"),
    )
    w = W_DockerWatcher("main", 60)
    w.initialize()
    w._work()
