from monda.classes.workers.worker_utils import start_worker_by_name, validate_worker_config
from monda.classes.workers.W_ConfigWatch import W_ConfigWatch


def test_validate_worker_config_ok(merge_worker):
    merge_worker("W_MDWatcher", "main", {"INTERVAL": 30})
    assert validate_worker_config() is True


def test_start_worker_by_name_disabled(merge_worker):
    merge_worker("W_MDWatcher", "main", {"INTERVAL": 30, "ENABLED": False})
    assert start_worker_by_name("W_MDWatcher", "main") is None


def test_start_worker_missing_instance():
    assert start_worker_by_name("W_MDWatcher", "nope") is None


def test_config_watch_flag():
    assert W_ConfigWatch.watch_config_changes is False
