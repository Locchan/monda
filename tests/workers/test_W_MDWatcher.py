from pathlib import Path

from monda.classes.workers.W_MDWatcher import W_MDWatcher
from monda.utils import status


def _prep(merge_worker, mdstat_path: Path, **extra):
    cfg = {"INTERVAL": 30, "ALERT_TARGET": "general", "MDSTAT_PATH": str(mdstat_path), **extra}
    merge_worker("W_MDWatcher", "main", cfg)
    w = W_MDWatcher("main", 30)
    assert w.initialize() is True
    return w


def test_parse_healthy(sample_text, tmp_path, merge_worker):
    path = tmp_path / "mdstat"
    path.write_text(sample_text("mdstat_healthy.txt"), encoding="utf-8")
    w = _prep(merge_worker, path)
    arrays = w._parse_mdstat(str(path))
    assert "md127" in arrays
    assert arrays["md127"]["failed_drives"] == 0
    w._work()
    detail = status.snapshot()["workers"]["W:MD_main"]["detail"]
    assert detail == "1/1 arrays healthy."
    assert status.snapshot()["workers"]["W:MD_main"]["color"] == "green"


def test_degraded_alerts_and_red(sample_text, tmp_path, merge_worker, led_dir):
    path = tmp_path / "mdstat"
    path.write_text(sample_text("mdstat_degraded.txt"), encoding="utf-8")
    w = _prep(merge_worker, path)
    w._work()
    snap = status.snapshot()["workers"]["W:MD_main"]
    assert snap["detail"] == "1/2 arrays healthy."
    assert snap["color"] == "red"
    assert list(led_dir.glob("alert_*.json"))


def test_inactive_alerts(sample_text, tmp_path, merge_worker, led_dir):
    path = tmp_path / "mdstat"
    path.write_text(sample_text("mdstat_inactive.txt"), encoding="utf-8")
    w = _prep(merge_worker, path)
    w._work()
    assert status.snapshot()["workers"]["W:MD_main"]["color"] == "red"
    assert list(led_dir.glob("alert_*.json"))


def test_ignore_array(sample_text, tmp_path, merge_worker, led_dir):
    path = tmp_path / "mdstat"
    path.write_text(sample_text("mdstat_degraded.txt"), encoding="utf-8")
    w = _prep(merge_worker, path, IGNORE=["md1"])
    w._work()
    snap = status.snapshot()["workers"]["W:MD_main"]
    assert snap["detail"] == "1/1 arrays healthy."
    assert snap["color"] == "green"


def test_missing_mdstat_initialize_still_ok(tmp_path, merge_worker):
    path = tmp_path / "missing_mdstat"
    w = _prep(merge_worker, path)
    assert w.initialized is True
