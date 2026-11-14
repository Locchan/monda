from datetime import datetime, timedelta

from monda.classes.workers.W_Cron import W_Cron
from monda.utils import status


def test_cron_init_ok(merge_worker):
    merge_worker(
        "W_Cron",
        "main",
        {
            "INTERVAL": 5,
            "JOBS": {
                "snap": {
                    "SCHEDULE": "*/15 * * * *",
                    "JOB_CLASS": "J_HikSnap",
                    "PARAMS": {"HIK_DEVICE": "cam4", "DEST_DIR": "/tmp/x"},
                }
            },
        },
    )
    w = W_Cron("main", 5)
    assert w.initialize() is True
    assert "1 job" in status.snapshot()["workers"]["W:Cron_main"]["detail"]


def test_cron_init_invalid_schedule(merge_worker):
    merge_worker(
        "W_Cron",
        "main",
        {"INTERVAL": 5, "JOBS": {"bad": {"SCHEDULE": "not-a-cron", "JOB_CLASS": "J_HikSnap"}}},
    )
    w = W_Cron("main", 5)
    assert w.initialize() is False


def test_cron_init_unknown_job_class(merge_worker):
    merge_worker(
        "W_Cron",
        "main",
        {"INTERVAL": 5, "JOBS": {"bad": {"SCHEDULE": "* * * * *", "JOB_CLASS": "J_Nope"}}},
    )
    w = W_Cron("main", 5)
    assert w.initialize() is False


def test_cron_init_empty_jobs(merge_worker):
    merge_worker("W_Cron", "main", {"INTERVAL": 5, "JOBS": {}})
    w = W_Cron("main", 5)
    assert w.initialize() is False


def test_cron_fires_due_job(merge_worker, monkeypatch):
    merge_worker(
        "W_Cron",
        "main",
        {
            "INTERVAL": 5,
            "JOBS": {
                "snap": {
                    "SCHEDULE": "* * * * *",
                    "JOB_CLASS": "J_HikSnap",
                    "PARAMS": {"HIK_DEVICE": "cam4", "DEST_DIR": "/tmp/x"},
                }
            },
        },
    )
    w = W_Cron("main", 5)
    assert w.initialize()
    called = {}

    def fake_spawn(job_name, job_class_name, params, silent):
        called["args"] = (job_name, job_class_name, params, silent)

    monkeypatch.setattr(w, "_spawn_job", fake_spawn)
    w._last_check = datetime.now() - timedelta(minutes=2)
    w._work()
    assert called["args"][0] == "snap"
    assert called["args"][1] == "J_HikSnap"
