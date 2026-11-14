"""Full live config-reload path using real W_MDWatcher + monda._supervise_once."""

from __future__ import annotations

import time

import pytest

import monda.classes.base.Worker as worker_mod
from monda.classes.workers import worker_utils
from monda.monda import _supervise_once
from monda.utils import status


@pytest.fixture(autouse=True)
def _fast_chunks(monkeypatch):
    monkeypatch.setattr(worker_mod, "_SLEEP_CHUNK_S", 1.0)
    real_sleep = time.sleep

    def fast_sleep(seconds):
        if seconds >= 0.4:
            return
        real_sleep(seconds)

    monkeypatch.setattr("monda.monda.time.sleep", fast_sleep)


def _wait_until(pred, timeout_s: float = 8.0, interval_s: float = 0.05) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(interval_s)
    raise AssertionError(f"condition not met within {timeout_s}s")


def test_full_reload_path_mid_sleep_restarts_with_new_config(
    merge_worker, live_merge_worker, led_dir, tmp_path, sample_text,
):
    healthy = tmp_path / "healthy"
    degraded = tmp_path / "degraded"
    healthy.write_text(sample_text("mdstat_healthy.txt"), encoding="utf-8")
    degraded.write_text(sample_text("mdstat_degraded.txt"), encoding="utf-8")

    merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5,
        "ALERT_TARGET": "general",
        "MDSTAT_PATH": str(healthy),
    })
    thread = worker_utils.start_worker_by_name("W_MDWatcher", "main")
    assert thread is not None and thread.is_alive()
    _wait_until(lambda: status.snapshot()["workers"]["W:MD_main"]["detail"] == "1/1 arrays healthy.")

    # Change config during inter-tick sleep (1s chunks)
    live_merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5,
        "ALERT_TARGET": "general",
        "MDSTAT_PATH": str(degraded),
    })
    _wait_until(lambda: not thread.is_alive(), timeout_s=4.0)

    alerts = list(led_dir.glob("alert_*.json"))
    assert alerts
    assert any(
        "restarted due to configuration change" in p.read_text(encoding="utf-8")
        for p in alerts
    )

    worker_threads = [(thread, "W_MDWatcher", "main")]
    _supervise_once(worker_threads)
    new_thread = worker_threads[0][0]
    assert new_thread is not None and new_thread is not thread and new_thread.is_alive()

    # Resurrected worker must be running with the new mdstat path
    _wait_until(
        lambda: status.snapshot()["workers"]["W:MD_main"]["detail"] == "1/2 arrays healthy.",
        timeout_s=8.0,
    )
    assert status.snapshot()["workers"]["W:MD_main"]["color"] == "red"

    live_merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5, "MDSTAT_PATH": str(degraded), "ENABLED": False, "ALERT_TARGET": "general",
    })
    _wait_until(lambda: not new_thread.is_alive(), timeout_s=4.0)
