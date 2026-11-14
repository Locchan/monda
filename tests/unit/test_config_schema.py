from monda.classes.jobs import ENABLED_JOBS
from monda.classes.workers import ENABLED_WORKERS
from monda.config_schema import JOB_SCHEMAS, WORKER_SCHEMAS, validate, Field


def test_every_enabled_worker_has_schema():
    missing = [k for k in ENABLED_WORKERS if k not in WORKER_SCHEMAS]
    assert missing == []


def test_every_enabled_job_has_schema():
    missing = [k for k in ENABLED_JOBS if k not in JOB_SCHEMAS]
    assert missing == []


def test_validate_required_missing():
    errors = validate({}, [Field("FOO", "foo", "str")])
    assert any("required" in e for e in errors)


def test_validate_type_mismatch():
    errors = validate({"FOO": "x"}, [Field("FOO", "foo", "int")])
    assert any("must be int" in e for e in errors)


def test_validate_optional_ok():
    errors = validate({}, [Field("FOO", "foo", "str", optional=True)])
    assert errors == []


def test_validate_ok():
    errors = validate({"FOO": 1}, [Field("FOO", "foo", "int")])
    assert errors == []
