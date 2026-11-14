import json

from helpers import activate_config, write_config_file
from monda.classes.workers.worker_utils import (
    start_all_workers,
    start_worker_by_name,
    validate_worker_config,
)
from monda.classes.workers.W_ConfigWatch import W_ConfigWatch


def test_validate_worker_config_ok(merge_worker):
    merge_worker("W_MDWatcher", "main", {"INTERVAL": 30})
    assert validate_worker_config() is True


def test_validate_unknown_worker_type(cfg_path, tmp_path):
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["WORKER_CONFIG"]["W_DoesNotExist"] = {"main": {"INTERVAL": 10}}
    write_config_file(cfg_path, data)
    activate_config(cfg_path)
    assert validate_worker_config() is False


def test_start_worker_unknown_type_returns_none_no_crash(cfg_path):
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["WORKER_CONFIG"]["W_DoesNotExist"] = {"main": {"INTERVAL": 10}}
    write_config_file(cfg_path, data)
    activate_config(cfg_path)
    assert start_worker_by_name("W_DoesNotExist", "main") is None


def test_start_all_workers_skips_unknown_and_alerts(cfg_path, led_dir, merge_worker):
    merge_worker("W_MDWatcher", "main", {"INTERVAL": 30, "ENABLED": False})
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["WORKER_CONFIG"]["W_GhostWorker"] = {"main": {"INTERVAL": 10}}
    write_config_file(cfg_path, data)
    activate_config(cfg_path)

    threads = start_all_workers()
    assert all(wt != "W_GhostWorker" for _, wt, _ in threads)

    alerts = list(led_dir.glob("alert_*.json"))
    assert alerts
    bodies = [p.read_text(encoding="utf-8") for p in alerts]
    assert any("W_GhostWorker" in b and "Misconfiguration" in b for b in bodies)


def test_start_worker_by_name_disabled(merge_worker):
    merge_worker("W_MDWatcher", "main", {"INTERVAL": 30, "ENABLED": False})
    assert start_worker_by_name("W_MDWatcher", "main") is None


def test_start_worker_missing_instance():
    assert start_worker_by_name("W_MDWatcher", "nope") is None


def test_config_watch_flag():
    assert W_ConfigWatch.watch_config_changes is False
