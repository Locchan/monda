"""Workers must fail fast on inaccessible/missing resources — never hang."""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from helpers import activate_config, configs_dir, make_base_config, write_config_file
from helpers_failfast import run_within
from monda.classes.workers.W_BackupWatcherBorg import W_BackupWatcherBorg
from monda.classes.workers.W_BackupWatcherRaw import W_BackupWatcherRaw
from monda.classes.workers.W_DockerWatcher import W_DockerWatcher
from monda.classes.workers.W_MDWatcher import W_MDWatcher
from monda.classes.workers.W_MondaStatus import W_MondaStatus
from monda.classes.workers.W_SSHLoginWatcher import W_SSHLoginWatcher
from monda.classes.workers.W_SystemdWatcher import W_SystemdWatcher
from monda.classes.workers.W_ZFSWatcher import W_ZFSWatcher
from monda.classes.workers.hik.W_HikProducer import W_HikProducer
from monda.classes.workers.telegram.W_TelegramBot import W_TelegramBot
from monda.utils import status

borg_mod = sys.modules[W_BackupWatcherBorg.__module__]
docker_mod = sys.modules[W_DockerWatcher.__module__]
systemd_mod = sys.modules[W_SystemdWatcher.__module__]
zfs_mod = sys.modules[W_ZFSWatcher.__module__]
ssh_mod = sys.modules[W_SSHLoginWatcher.__module__]
hik_prod_mod = sys.modules[W_HikProducer.__module__]
tg_mod = sys.modules[W_TelegramBot.__module__]
status_mod = sys.modules[W_MondaStatus.__module__]


def _assert_quick(fn, budget_s: float = 2.0):
    return run_within(fn, budget_s=budget_s)


# ── MD ───────────────────────────────────────────────────────────────────────

def test_md_missing_mdstat_init_and_work_return_quickly(tmp_path, merge_worker):
    missing = tmp_path / "no_such_mdstat"
    merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 30, "MDSTAT_PATH": str(missing), "ALERT_TARGET": "general",
    })
    w = W_MDWatcher("main", 30)

    assert _assert_quick(w.initialize) is True
    _assert_quick(w._work)  # logs error, does not raise/hang


def test_md_unreadable_mdstat_work_returns_quickly(tmp_path, merge_worker, monkeypatch):
    path = tmp_path / "mdstat"
    path.write_text("Personalities :\nunused devices: <none>\n", encoding="utf-8")
    merge_worker("W_MDWatcher", "main", {"INTERVAL": 30, "MDSTAT_PATH": str(path)})
    w = W_MDWatcher("main", 30)
    assert w.initialize()

    def boom(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr("builtins.open", boom)
    _assert_quick(w._work)


# ── ZFS ──────────────────────────────────────────────────────────────────────

def test_zfs_missing_binary_fails_init_quickly(merge_worker, monkeypatch):
    merge_worker("W_ZFSWatcher", "main", {"INTERVAL": 30})
    monkeypatch.setattr(zfs_mod.shutil, "which", lambda _: None)
    w = W_ZFSWatcher("main", 30)
    assert _assert_quick(w.initialize) is False


def test_zfs_status_error_work_returns_quickly(merge_worker, monkeypatch):
    merge_worker("W_ZFSWatcher", "main", {"INTERVAL": 30})
    monkeypatch.setattr(zfs_mod.shutil, "which", lambda _: "/sbin/zpool")
    monkeypatch.setattr(
        zfs_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="permission denied"),
    )
    w = W_ZFSWatcher("main", 30)
    # init may fail or succeed depending on exception handling
    _assert_quick(w.initialize)
    _assert_quick(w._work)


def test_zfs_subprocess_uses_timeout(merge_worker, monkeypatch):
    merge_worker("W_ZFSWatcher", "main", {"INTERVAL": 30})
    monkeypatch.setattr(zfs_mod.shutil, "which", lambda _: "/sbin/zpool")
    seen = {}

    def fake_run(*a, **k):
        seen.update(k)
        return SimpleNamespace(returncode=0, stdout="no pools available\n", stderr="no pools available")

    monkeypatch.setattr(zfs_mod.subprocess, "run", fake_run)
    w = W_ZFSWatcher("main", 30)
    w.initialize()
    assert seen.get("timeout") == 30


# ── Docker ───────────────────────────────────────────────────────────────────

def test_docker_daemon_unreachable_work_returns_quickly(merge_worker, monkeypatch):
    merge_worker("W_DockerWatcher", "main", {"INTERVAL": 60})
    monkeypatch.setattr(
        docker_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="Cannot connect"),
    )
    w = W_DockerWatcher("main", 60)
    assert _assert_quick(w.initialize) is True
    _assert_quick(w._work)


def test_docker_subprocess_timeout_propagates_and_returns(merge_worker, monkeypatch):
    merge_worker("W_DockerWatcher", "main", {"INTERVAL": 60})

    def hang(*a, **k):
        raise docker_mod.subprocess.TimeoutExpired(cmd=a[0] if a else "docker", timeout=30)

    monkeypatch.setattr(docker_mod.subprocess, "run", hang)
    w = W_DockerWatcher("main", 60)
    w.initialize()
    _assert_quick(w._work)


def test_docker_subprocess_uses_timeout(merge_worker, monkeypatch):
    merge_worker("W_DockerWatcher", "main", {"INTERVAL": 60})
    seen = {}

    def fake_run(cmd, **k):
        seen["timeout"] = k.get("timeout")
        if cmd[:3] == ["docker", "ps", "-a"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(docker_mod.subprocess, "run", fake_run)
    w = W_DockerWatcher("main", 60)
    w.initialize()
    w._work()
    assert seen["timeout"] == 30


# ── Systemd ──────────────────────────────────────────────────────────────────

def test_systemctl_failure_work_returns_quickly(merge_worker, monkeypatch):
    merge_worker("W_SystemdWatcher", "main", {"INTERVAL": 60})
    monkeypatch.setattr(
        systemd_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="offline"),
    )
    w = W_SystemdWatcher("main", 60)
    w.initialize()
    _assert_quick(w._work)


def test_systemctl_timeout_work_returns_quickly(merge_worker, monkeypatch):
    merge_worker("W_SystemdWatcher", "main", {"INTERVAL": 60})

    def hang(*a, **k):
        raise systemd_mod.subprocess.TimeoutExpired(cmd="systemctl", timeout=30)

    monkeypatch.setattr(systemd_mod.subprocess, "run", hang)
    w = W_SystemdWatcher("main", 60)
    w.initialize()
    _assert_quick(w._work)


# ── Backup raw / borg ────────────────────────────────────────────────────────

def test_raw_backup_nonexistent_path_work_returns_quickly(tmp_path, merge_worker, led_dir):
    merge_worker("W_BackupWatcherRaw", "main", {
        "INTERVAL": 10,
        "ALERT_TARGET": "general",
        "BACKUPS": {
            "gone": {
                "PATH": str(tmp_path / "does-not-exist"),
                "EXPECTED_PERIOD_MINUTES": 1,
                "PERMITTED_LAG_MINUTES": 1,
            }
        },
    })
    w = W_BackupWatcherRaw("main", 10)
    assert _assert_quick(w.initialize) is True
    _assert_quick(w._work)
    assert status.snapshot()["workers"]["W:BkpRaw_main"]["color"] == "yellow"


def test_borg_nonexistent_repo_work_returns_quickly(tmp_path, merge_worker, monkeypatch, led_dir):
    merge_worker("W_BackupWatcherBorg", "main", {
        "INTERVAL": 10,
        "ALERT_TARGET": "general",
        "BACKUPS": {
            "repo": {
                "PATH": str(tmp_path / "missing-repo"),
                "EXPECTED_PERIOD_MINUTES": 1,
                "PERMITTED_LAG_MINUTES": 1,
            }
        },
    })
    monkeypatch.setattr(
        borg_mod.subprocess, "run",
        lambda *a, **k: SimpleNamespace(returncode=2, stdout="", stderr="Repository not found"),
    )
    w = W_BackupWatcherBorg("main", 10)
    assert _assert_quick(w.initialize) is True
    _assert_quick(w._work)
    assert list(led_dir.glob("alert_*.json"))


def test_borg_subprocess_uses_timeout(tmp_path, merge_worker, monkeypatch):
    merge_worker("W_BackupWatcherBorg", "main", {
        "INTERVAL": 10,
        "BACKUPS": {
            "repo": {
                "PATH": str(tmp_path / "r"),
                "EXPECTED_PERIOD_MINUTES": 1,
                "PERMITTED_LAG_MINUTES": 1,
            }
        },
    })
    seen = {}

    def fake_run(*a, **k):
        seen["timeout"] = k.get("timeout")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"archives": []}), stderr="")

    monkeypatch.setattr(borg_mod.subprocess, "run", fake_run)
    w = W_BackupWatcherBorg("main", 10)
    w.initialize()
    w._work()
    assert seen["timeout"] == 60


# ── SSH ──────────────────────────────────────────────────────────────────────

def test_ssh_unreadable_log_work_returns_quickly(tmp_path, merge_worker, monkeypatch):
    log = tmp_path / "auth.log"
    log.write_text("", encoding="utf-8")
    merge_worker("W_SSHLoginWatcher", "main", {
        "INTERVAL": 10, "LOG_PATH": str(log), "ALERT_TARGET": "general",
    })
    w = W_SSHLoginWatcher("main", 10)
    assert w.initialize()

    def boom_stat(*a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(ssh_mod.os, "stat", boom_stat)
    _assert_quick(w._work)


def test_ssh_journalctl_timeout_on_init(merge_worker, monkeypatch, tmp_path):
    # No LOG_PATH → journalctl path
    merge_worker("W_SSHLoginWatcher", "main", {"INTERVAL": 10})
    monkeypatch.setattr(ssh_mod.os.path, "isfile", lambda p: False)

    def hang(*a, **k):
        raise ssh_mod.subprocess.TimeoutExpired(cmd="journalctl", timeout=30)

    monkeypatch.setattr(ssh_mod.subprocess, "run", hang)
    w = W_SSHLoginWatcher("main", 10)
    assert _assert_quick(w.initialize) is False


# ── MondaStatus ──────────────────────────────────────────────────────────────

def test_status_bind_failure_fails_init_quickly(merge_worker, monkeypatch):
    merge_worker("W_MondaStatus", "main", {"PORT": 9, "INTERVAL": 10})

    def boom(*a, **k):
        raise OSError("Address already in use")

    monkeypatch.setattr(status_mod, "_ReuseTCPServer", boom)
    w = W_MondaStatus("main", 10)
    assert _assert_quick(w.initialize) is False


# ── Telegram ─────────────────────────────────────────────────────────────────

def test_telegram_api_unreachable_fails_init_quickly(cfg_path, tmp_path, monkeypatch, led_dir):
    data = make_base_config(
        TELEGRAM={"BOT_TOKEN": "1:TEST", "CHAT_IDS": [1]},
        WORKER_CONFIG={"W_TelegramBot": {"monbot": {"INTERVAL": 5}}},
        LED_TARGETS={"general": {"BASEDIR": str(led_dir)}},
    )
    write_config_file(cfg_path, data)
    activate_config(cfg_path)

    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(tg_mod.requests, "get", boom)
    w = W_TelegramBot("monbot", 5)
    assert _assert_quick(w.initialize) is False


def test_telegram_getupdates_error_work_returns_quickly(cfg_path, tmp_path, monkeypatch, led_dir):
    data = make_base_config(
        TELEGRAM={"BOT_TOKEN": "1:TEST", "CHAT_IDS": [1]},
        WORKER_CONFIG={"W_TelegramBot": {"monbot": {"INTERVAL": 5}}},
        LED_TARGETS={"general": {"BASEDIR": str(led_dir)}},
    )
    write_config_file(cfg_path, data)
    activate_config(cfg_path)

    class OkMe:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": {"username": "bot"}}

    monkeypatch.setattr(tg_mod.requests, "get", lambda *a, **k: OkMe())
    w = W_TelegramBot("monbot", 5)
    assert w.initialize()

    def boom(*a, **k):
        raise requests.Timeout("slow")

    monkeypatch.setattr(tg_mod.requests, "get", boom)
    _assert_quick(w._work)


def test_telegram_requests_use_finite_timeout():
    src = inspect.getsource(W_TelegramBot._initialize)
    assert "timeout=" in src
    src2 = inspect.getsource(W_TelegramBot._get_updates)
    assert "timeout=" in src2


# ── Hik producer ─────────────────────────────────────────────────────────────

def test_hik_producer_bad_device_fails_quickly(cfg_path, tmp_path, merge_worker):
    data = json.loads((configs_dir() / "camera_site.json").read_text(encoding="utf-8"))
    for name, tgt in data["LED_TARGETS"].items():
        p = tmp_path / f"led-{name}"
        p.mkdir(exist_ok=True)
        tgt["BASEDIR"] = str(p)
    write_config_file(cfg_path, data)
    activate_config(cfg_path)
    merge_worker("W_HikProducer", "ghost", {"DEVICE": "missing", "INTERVAL": 30})
    w = W_HikProducer("ghost", 30)

    def go():
        with pytest.raises(RuntimeError, match="not found"):
            w.initialize()

    _assert_quick(go)


def test_hik_producer_stream_uses_connect_timeout(cfg_path, tmp_path, monkeypatch):
    data = json.loads((configs_dir() / "camera_site.json").read_text(encoding="utf-8"))
    for name, tgt in data["LED_TARGETS"].items():
        p = tmp_path / f"led-{name}"
        p.mkdir(exist_ok=True)
        tgt["BASEDIR"] = str(p)
    write_config_file(cfg_path, data)
    activate_config(cfg_path)

    w = W_HikProducer("cam4", 30)
    assert w.initialize()
    seen = {}

    class FakeResp:
        status_code = 503

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self):
            return iter(())

    def fake_get(*a, **k):
        seen["timeout"] = k.get("timeout")
        return FakeResp()

    monkeypatch.setattr(hik_prod_mod.requests, "get", fake_get)
    # _work loops the generator; with 503 it returns immediately
    _assert_quick(w._work)
    assert seen["timeout"] == (10, None)


def test_hik_producer_connection_error_work_returns_quickly(cfg_path, tmp_path, monkeypatch):
    data = json.loads((configs_dir() / "camera_site.json").read_text(encoding="utf-8"))
    for name, tgt in data["LED_TARGETS"].items():
        p = tmp_path / f"led-{name}"
        p.mkdir(exist_ok=True)
        tgt["BASEDIR"] = str(p)
    write_config_file(cfg_path, data)
    activate_config(cfg_path)
    w = W_HikProducer("cam4", 30)
    w.initialize()

    def boom(*a, **k):
        raise requests.ConnectionError("camera offline")

    monkeypatch.setattr(hik_prod_mod.requests, "get", boom)

    def go():
        with pytest.raises(requests.ConnectionError):
            w._work()

    _assert_quick(go)
