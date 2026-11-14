import time
from pathlib import Path

import pytest

from monda.classes.base.Worker import Worker, _SLEEP_CHUNK_S
from monda.utils import status


class W_TestWorker(Worker):
    worker_class_name = "W_TestWorker"
    worker_class_name_short = "W:Test"

    def _initialize(self) -> bool:
        self._update_status("Ready.")
        return True

    def _work(self) -> None:
        self._update_status("Worked.")


# Register schema dynamically for this fake worker
@pytest.fixture(autouse=True)
def _register_test_worker_schema(monkeypatch):
    from monda import config_schema
    from monda.config_schema import Field, WorkerSchema

    monkeypatch.setitem(
        config_schema.WORKER_SCHEMAS,
        "W_TestWorker",
        WorkerSchema(
            "test",
            [
                Field("INTERVAL", "i", "int", 1),
                Field("ALERT_TARGET", "t", "str", "general", optional=True),
                Field("IGNORE_OVERLAP", "io", "bool", False, optional=True),
                Field("FOO", "f", "str", optional=True),
                Field("ENABLED", "e", "bool", True, optional=True),
            ],
        ),
    )


def test_initialize_success(merge_worker):
    merge_worker("W_TestWorker", "main", {"INTERVAL": 1, "FOO": "bar"})
    w = W_TestWorker("main", 1)
    assert w.initialize() is True
    assert w.initialized is True
    assert w.config["FOO"] == "bar"
    assert status.snapshot()["workers"]["W:Test_main"]["detail"] in ("Ready.", "Starting...")


def test_initialize_missing_config():
    w = W_TestWorker("missing", 1)
    assert w.initialize() is False
    snap = status.snapshot()["workers"]["W:Test_missing"]
    assert snap["color"] == "red"
    assert "No config" in (snap["crash_error"] or "")


def test_initialize_disabled_purges_status(merge_worker):
    merge_worker("W_TestWorker", "main", {"INTERVAL": 1, "ENABLED": False})
    w = W_TestWorker("main", 1)
    assert w.initialize() is True
    assert w._disabled is True
    assert "W:Test_main" not in status.snapshot()["workers"]
    assert w.run() is None


def test_refresh_config_changed_and_disabled(merge_worker, cfg_path: Path):
    merge_worker("W_TestWorker", "main", {"INTERVAL": 1, "FOO": "a"})
    w = W_TestWorker("main", 1)
    assert w.initialize()
    assert w._refresh_config() == "ok"

    merge_worker("W_TestWorker", "main", {"INTERVAL": 1, "FOO": "b"})
    assert w._refresh_config() == "changed"

    merge_worker("W_TestWorker", "main", {"INTERVAL": 1, "FOO": "b", "ENABLED": False})
    assert w._refresh_config() == "disabled"


def test_config_watch_false_skips_refresh(merge_worker):
    class W_NoWatch(W_TestWorker):
        worker_class_name = "W_TestWorker"
        watch_config_changes = False

    merge_worker("W_TestWorker", "main", {"INTERVAL": 1, "FOO": "a"})
    w = W_NoWatch("main", 1)
    w.initialize()
    merge_worker("W_TestWorker", "main", {"INTERVAL": 1, "FOO": "b"})
    assert w._refresh_config() == "ok"


def test_sleep_until_overslept_returns_immediately():
    w = W_TestWorker("main", 1)
    w.config = {}
    assert w._sleep_until(time.monotonic() - 10) == "ok"


def test_sleep_until_respects_deadline(monkeypatch):
    w = W_TestWorker("main", 30)
    w.watch_config_changes = False
    sleeps: list[float] = []

    def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(time, "sleep", fake_sleep)
    deadline = time.monotonic() + 2.5
    # freeze monotonic progression roughly by returning deadline after first call
    values = [deadline - 2.5, deadline - 2.5, deadline + 0.1]

    def fake_mono():
        return values.pop(0) if values else deadline + 1

    monkeypatch.setattr(time, "monotonic", fake_mono)
    assert w._sleep_until(deadline) == "ok"
    assert sleeps
    assert sleeps[0] == pytest.approx(2.5)


def test_sleep_until_chunks_and_detects_change(merge_worker, monkeypatch):
    merge_worker("W_TestWorker", "main", {"INTERVAL": 30, "FOO": "a"})
    w = W_TestWorker("main", 30)
    w.initialize()

    monkeypatch.setattr(time, "sleep", lambda s: None)
    # remaining > chunk, then change detected
    calls = {"n": 0}

    def mono():
        calls["n"] += 1
        # first remaining large, after sleep still large enough to check
        return 1000.0 if calls["n"] < 3 else 1000.0

    monkeypatch.setattr(time, "monotonic", mono)
    # force remaining > 5 by deadline far ahead
    deadline = 1000.0 + _SLEEP_CHUNK_S + 10

    def refresh():
        return "changed"

    monkeypatch.setattr(w, "_refresh_config", refresh)
    assert w._sleep_until(deadline) == "changed"


def test_stop_for_config_changed_marks_reload_and_alerts(merge_worker, led_dir, monkeypatch):
    merge_worker("W_TestWorker", "main", {"INTERVAL": 1, "ALERT_TARGET": "general"})
    w = W_TestWorker("main", 1)
    w.initialize()
    future = time.monotonic() + 60
    assert w._stop_for_config("changed", sleep_until=future) is True
    assert status.consume_config_reload("W_TestWorker", "main") is True
    assert status.consume_pending_sleep("W_TestWorker", "main") == pytest.approx(future)
    assert list(led_dir.glob("alert_*.json"))


def test_overlapped_deadline_errors_and_reschedules(merge_worker, led_dir, monkeypatch):
    merge_worker("W_TestWorker", "main", {"INTERVAL": 10, "ALERT_TARGET": "general"})
    w = W_TestWorker("main", 10)
    w.initialize()

    start = 1000.0
    interval = 10.0
    next_due = start + interval
    monkeypatch.setattr(time, "monotonic", lambda: start + 15)
    next_due = w._finish_tick(next_due, interval)

    assert w._status_entry.overlapped is True
    assert w._status_entry.color() == "red"
    assert next_due == pytest.approx(start + 15 + interval)
    assert list(led_dir.glob("alert_*.json"))


def test_overlapped_clears_after_successful_cycle(merge_worker, led_dir, monkeypatch):
    merge_worker("W_TestWorker", "main", {"INTERVAL": 10, "ALERT_TARGET": "general"})
    w = W_TestWorker("main", 10)
    w.initialize()

    start = 1000.0
    interval = 10.0
    next_due = start + interval
    monkeypatch.setattr(time, "monotonic", lambda: start + 15)
    next_due = w._finish_tick(next_due, interval)
    assert w._status_entry.overlapped is True
    assert w._status_entry.color() == "red"

    # Next cycle finishes before its deadline → green again.
    scheduled = next_due  # start+15+10; work starts then, deadline = that + interval
    work_start = next_due
    next_due = work_start + interval
    monkeypatch.setattr(time, "monotonic", lambda: work_start + 1)
    next_due = w._finish_tick(next_due, interval)
    assert w._status_entry.overlapped is False
    assert w._status_entry.color() == "green"
    assert next_due == pytest.approx(work_start + interval)
    assert next_due == pytest.approx(scheduled + interval)


def test_ignore_overlap_skips_alert_and_red(merge_worker, led_dir, monkeypatch, caplog):
    merge_worker(
        "W_TestWorker",
        "main",
        {"INTERVAL": 10, "ALERT_TARGET": "general", "IGNORE_OVERLAP": True},
    )
    w = W_TestWorker("main", 10)
    w.initialize()

    start = 1000.0
    interval = 10.0
    next_due = start + interval
    monkeypatch.setattr(time, "monotonic", lambda: start + 15)
    with caplog.at_level("ERROR"):
        next_due = w._finish_tick(next_due, interval)

    assert w._status_entry.overlapped is False
    assert w._status_entry.color() == "green"
    assert next_due == pytest.approx(start + 15 + interval)
    assert not list(led_dir.glob("alert_*.json"))
    assert not any("overlapped" in r.getMessage().lower() or "deadline" in r.getMessage().lower()
                   for r in caplog.records)


def test_ignore_overlap_false_still_alerts(merge_worker, led_dir, monkeypatch):
    merge_worker(
        "W_TestWorker",
        "main",
        {"INTERVAL": 10, "ALERT_TARGET": "general", "IGNORE_OVERLAP": False},
    )
    w = W_TestWorker("main", 10)
    w.initialize()

    start = 1000.0
    interval = 10.0
    monkeypatch.setattr(time, "monotonic", lambda: start + 15)
    w._finish_tick(start + interval, interval)
    assert w._status_entry.overlapped is True
    assert w._status_entry.color() == "red"
    assert list(led_dir.glob("alert_*.json"))
