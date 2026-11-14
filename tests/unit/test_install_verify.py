"""Tests for post-install consistency checks."""

from pathlib import Path

import monda.install_verify as iv
from monda.classes.jobs import ENABLED_JOBS
from monda.classes.workers import ENABLED_WORKERS
from monda.config_schema import JOB_SCHEMAS, WORKER_SCHEMAS


def test_verify_clean_install_has_no_errors():
    assert iv.verify() == []


def test_enabled_workers_match_schemas():
    assert set(ENABLED_WORKERS) == set(WORKER_SCHEMAS)


def test_enabled_jobs_match_schemas():
    assert set(ENABLED_JOBS) == set(JOB_SCHEMAS)


def test_orphan_modules_detects_stray_worker(tmp_path, monkeypatch):
    workers_dir = tmp_path / "workers"
    workers_dir.mkdir()
    (workers_dir / "W_Ghost.py").write_text("# orphan\n", encoding="utf-8")
    (workers_dir / "W_Real.py").write_text("# ok\n", encoding="utf-8")
    orphans = iv._orphan_modules(workers_dir, "W", {"W_Real"})
    assert any(Path(p).name == "W_Ghost.py" for p in orphans)
    assert not any(Path(p).name == "W_Real.py" for p in orphans)


def test_verify_reports_missing_status_api(monkeypatch):
    import monda.utils.status as status_mod

    monkeypatch.delattr(status_mod, "consume_config_reload", raising=False)
    errs = iv.verify()
    assert any("consume_config_reload" in e for e in errs)
