import time

import pytest

from monda.classes.base.Job import Job
from monda.utils import status


class J_TestJob(Job):
    job_class_name = "J_TestJob"
    job_class_name_short = "J:Test"

    def __init__(self, *a, fail: bool = False, **k):
        super().__init__(*a, **k)
        self._fail = fail

    def _initialize(self) -> bool:
        return True

    def _work(self) -> None:
        if self._fail:
            raise RuntimeError("job boom")


@pytest.fixture(autouse=True)
def _register_test_job_schema(monkeypatch):
    from monda import config_schema
    from monda.config_schema import Field, JobSchema

    monkeypatch.setitem(
        config_schema.JOB_SCHEMAS,
        "J_TestJob",
        JobSchema(
            "test",
            [
                Field("FOO", "f", "str"),
                Field("ENABLED", "e", "bool", True, optional=True),
            ],
        ),
    )


def test_initialize_success(merge_job):
    merge_job("J_TestJob", {"main": {"FOO": "bar"}})
    j = J_TestJob("main")
    assert j.initialize() is True
    assert j.config["FOO"] == "bar"


def test_initialize_validation_failure(merge_job):
    merge_job("J_TestJob", {"main": {}})  # missing FOO
    j = J_TestJob("main")
    assert j.initialize() is False


def test_runtime_config_overrides_static(merge_job):
    merge_job("J_TestJob", {"main": {"FOO": "static"}})
    j = J_TestJob("main", {"FOO": "runtime"})
    assert j.initialize() is True
    assert j.config["FOO"] == "runtime"


def test_class_disabled(merge_job):
    merge_job("J_TestJob", {"ENABLED": False, "main": {"FOO": "x"}})
    j = J_TestJob("main")
    assert j.initialize() is True
    assert j.run() is None


def test_run_success_updates_status(merge_job):
    merge_job("J_TestJob", {"main": {"FOO": "x"}})
    j = J_TestJob("main")
    assert j.initialize()
    t = j.run()
    assert t is not None
    t.join(timeout=2)
    entry = status.snapshot()["jobs"]["J_TestJob/main"]
    assert entry["last_run_ok"] is True
    assert "success" in entry["detail"]


def test_run_failure_alerts(merge_job, led_dir):
    merge_job("J_TestJob", {"main": {"FOO": "x"}})
    j = J_TestJob("main", fail=True)
    assert j.initialize()
    t = j.run()
    t.join(timeout=2)
    entry = status.snapshot()["jobs"]["J_TestJob/main"]
    assert entry["last_run_ok"] is False
    assert list(led_dir.glob("alert_*.json"))
