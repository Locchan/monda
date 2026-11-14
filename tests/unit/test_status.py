import time

from monda.utils import status


def test_worker_color_green_by_default():
    entry = status.WorkerEntry(name="W:X_main")
    assert entry.color() == "green"


def test_worker_color_red_on_crash():
    entry = status.WorkerEntry(name="W:X_main", crashed_at=time.time(), crash_error="boom")
    assert entry.color() == "red"


def test_worker_color_red_on_error_flag():
    entry = status.WorkerEntry(name="W:X_main", error=True)
    assert entry.color() == "red"


def test_worker_color_yellow_on_warning():
    entry = status.WorkerEntry(name="W:X_main", warning=True)
    assert entry.color() == "yellow"


def test_worker_color_yellow_after_recent_restart():
    entry = status.WorkerEntry(name="W:X_main", last_restart_at=time.time(), restart_count=1)
    assert entry.color() == "yellow"


def test_get_or_create_and_remove_worker():
    e1, is_new = status.get_or_create_worker("W:X_main")
    assert is_new is True
    e2, is_new2 = status.get_or_create_worker("W:X_main")
    assert is_new2 is False
    assert e1 is e2
    status.remove_worker("W:X_main")
    assert "W:X_main" not in status.snapshot()["workers"]


def test_config_reload_mark_consume_with_sleep():
    status.mark_config_reload("W_MDWatcher", "main", sleep_until=123.0)
    assert status.consume_config_reload("W_MDWatcher", "main") is True
    assert status.consume_config_reload("W_MDWatcher", "main") is False
    # sleep pending is independent consume
    status.mark_config_reload("W_MDWatcher", "main", sleep_until=456.0)
    assert status.consume_pending_sleep("W_MDWatcher", "main") == 456.0
    assert status.consume_pending_sleep("W_MDWatcher", "main") is None


def test_job_color_red_on_failure():
    entry = status.JobEntry(name="J_X/main", last_run_ok=False)
    assert entry.color() == "red"
    entry.last_run_ok = True
    assert entry.color() == "green"
