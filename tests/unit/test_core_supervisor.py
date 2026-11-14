"""Core daemon paths: monda._supervise_once, Worker crash/reload LED, start helpers."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import monda.classes.base.Worker as worker_mod
from monda.classes.workers.W_MDWatcher import W_MDWatcher
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


def _alert_messages(led_dir: Path) -> list[str]:
    return [
        json.loads(p.read_text(encoding="utf-8"))["message"]
        for p in sorted(led_dir.glob("alert_*.json"))
    ]


def _start_md(merge_worker, mdstat: Path, **extra) -> object:
    merge_worker(
        "W_MDWatcher",
        "main",
        {
            "INTERVAL": 5,
            "ALERT_TARGET": "general",
            "MDSTAT_PATH": str(mdstat),
            **extra,
        },
    )
    thread = worker_utils.start_worker_by_name("W_MDWatcher", "main")
    assert thread is not None and thread.is_alive()
    _wait_until(lambda: "arrays healthy" in status.snapshot()["workers"]["W:MD_main"]["detail"])
    return thread


def test_crash_led_and_supervise_once_resurrects(
    merge_worker, live_merge_worker, led_dir, tmp_path, sample_text, monkeypatch,
):
    mdstat = tmp_path / "mdstat"
    mdstat.write_text(sample_text("mdstat_healthy.txt"), encoding="utf-8")
    thread = _start_md(merge_worker, mdstat)

    # Crash mid-sleep via real _run BaseException handler (_refresh_config runs every chunk).
    real_refresh = W_MDWatcher._refresh_config

    def boom(self):
        raise RuntimeError("intentional crash")

    monkeypatch.setattr(W_MDWatcher, "_refresh_config", boom)
    _wait_until(lambda: not thread.is_alive(), timeout_s=4.0)
    monkeypatch.setattr(W_MDWatcher, "_refresh_config", real_refresh)

    msgs = _alert_messages(led_dir)
    assert any(
        m == "Worker W:MD_main crashed. Check monda logs." for m in msgs
    ), msgs
    snap = status.snapshot()["workers"]["W:MD_main"]
    assert snap["color"] == "red"
    assert "intentional crash" in (snap["crash_error"] or "")

    before = snap["restart_count"]
    worker_threads = [(thread, "W_MDWatcher", "main")]
    _supervise_once(worker_threads)  # real monda supervisor pass

    new_thread = worker_threads[0][0]
    assert new_thread is not None and new_thread is not thread and new_thread.is_alive()
    _wait_until(lambda: "arrays healthy" in status.snapshot()["workers"]["W:MD_main"]["detail"])
    after = status.snapshot()["workers"]["W:MD_main"]
    assert after["restart_count"] == before + 1
    assert after["color"] == "yellow"

    live_merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5, "MDSTAT_PATH": str(mdstat), "ENABLED": False, "ALERT_TARGET": "general",
    })
    _wait_until(lambda: not new_thread.is_alive(), timeout_s=4.0)


def test_config_reload_led_and_supervise_once_keeps_green(
    merge_worker, live_merge_worker, led_dir, tmp_path, sample_text,
):
    healthy = tmp_path / "healthy"
    degraded = tmp_path / "degraded"
    healthy.write_text(sample_text("mdstat_healthy.txt"), encoding="utf-8")
    degraded.write_text(sample_text("mdstat_degraded.txt"), encoding="utf-8")

    thread = _start_md(merge_worker, healthy)
    assert status.snapshot()["workers"]["W:MD_main"]["detail"] == "1/1 arrays healthy."

    # Live config change while sleeping (preserves reload mark + status)
    live_merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5,
        "ALERT_TARGET": "general",
        "MDSTAT_PATH": str(degraded),
    })
    _wait_until(lambda: not thread.is_alive(), timeout_s=4.0)

    msgs = _alert_messages(led_dir)
    assert any(
        m == "Worker W:MD_main restarted due to configuration change." for m in msgs
    ), msgs
    assert not any("crashed" in m.lower() for m in msgs)

    before = status.snapshot()["workers"]["W:MD_main"]["restart_count"]
    worker_threads = [(thread, "W_MDWatcher", "main")]
    _supervise_once(worker_threads)

    new_thread = worker_threads[0][0]
    assert new_thread is not None and new_thread is not thread and new_thread.is_alive()

    # New instance must apply the new MDSTAT_PATH (degraded → red x/y)
    _wait_until(
        lambda: status.snapshot()["workers"]["W:MD_main"]["detail"] == "1/2 arrays healthy.",
        timeout_s=8.0,
    )
    after = status.snapshot()["workers"]["W:MD_main"]
    assert after["restart_count"] == before  # config reload is not crash recovery
    assert after["color"] == "red"  # unhealthy arrays, not yellow restart

    live_merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5, "MDSTAT_PATH": str(degraded), "ENABLED": False, "ALERT_TARGET": "general",
    })
    _wait_until(lambda: not new_thread.is_alive(), timeout_s=4.0)


def test_supervise_once_skips_disabled(merge_worker, tmp_path, sample_text):
    mdstat = tmp_path / "mdstat"
    mdstat.write_text(sample_text("mdstat_healthy.txt"), encoding="utf-8")
    merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5, "MDSTAT_PATH": str(mdstat), "ENABLED": False,
    })
    worker_threads = [(None, "W_MDWatcher", "main")]
    _supervise_once(worker_threads)
    assert worker_threads[0][0] is None


def test_supervise_once_retries_null_thread(merge_worker, tmp_path, sample_text, live_merge_worker):
    mdstat = tmp_path / "mdstat"
    mdstat.write_text(sample_text("mdstat_healthy.txt"), encoding="utf-8")
    merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5, "MDSTAT_PATH": str(mdstat), "ALERT_TARGET": "general",
    })
    worker_threads = [(None, "W_MDWatcher", "main")]
    _supervise_once(worker_threads)
    new_thread = worker_threads[0][0]
    assert new_thread is not None and new_thread.is_alive()
    _wait_until(lambda: "W:MD_main" in status.snapshot()["workers"])

    live_merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5, "MDSTAT_PATH": str(mdstat), "ENABLED": False, "ALERT_TARGET": "general",
    })
    _wait_until(lambda: not new_thread.is_alive(), timeout_s=4.0)


def test_supervise_once_skips_removed_instance(
    merge_worker, cfg_path, tmp_path, sample_text,
):
    from helpers import write_config_file

    mdstat = tmp_path / "mdstat"
    mdstat.write_text(sample_text("mdstat_healthy.txt"), encoding="utf-8")
    thread = _start_md(merge_worker, mdstat)

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["WORKER_CONFIG"]["W_MDWatcher"].pop("main", None)
    write_config_file(cfg_path, data)
    import monda.utils.misc as misc
    misc._config_mtime = None
    misc.read_config()

    # Real path: missing instance → _refresh_config "disabled" → clean stop
    _wait_until(lambda: not thread.is_alive(), timeout_s=4.0)

    worker_threads = [(thread, "W_MDWatcher", "main")]
    _supervise_once(worker_threads)
    assert worker_threads[0][0] is thread


def test_start_all_workers_uses_real_registry(merge_worker, tmp_path, sample_text, live_merge_worker):
    mdstat = tmp_path / "mdstat"
    mdstat.write_text(sample_text("mdstat_healthy.txt"), encoding="utf-8")
    merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5, "MDSTAT_PATH": str(mdstat), "ALERT_TARGET": "general",
    })
    threads = worker_utils.start_all_workers()
    assert len(threads) == 1
    t, wtype, name = threads[0]
    assert (wtype, name) == ("W_MDWatcher", "main")
    assert t is not None and t.is_alive()
    live_merge_worker("W_MDWatcher", "main", {
        "INTERVAL": 5, "MDSTAT_PATH": str(mdstat), "ENABLED": False, "ALERT_TARGET": "general",
    })
    _wait_until(lambda: not t.is_alive(), timeout_s=4.0)
