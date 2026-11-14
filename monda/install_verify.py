"""Post-install consistency checks — catch mixed/partial package upgrades."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _orphan_modules(package_dir: Path, prefix: str, enabled: set[str]) -> list[str]:
    """Return top-level ``{prefix}_*.py`` stems not listed in ``enabled``."""
    orphans: list[str] = []
    if not package_dir.is_dir():
        return [f"missing package directory: {package_dir}"]
    for py in sorted(package_dir.glob(f"{prefix}_*.py")):
        name = py.stem
        if name not in enabled:
            orphans.append(str(py))
    return orphans


def verify() -> list[str]:
    """Return human-readable errors; empty list means the install looks consistent."""
    errors: list[str] = []

    try:
        import monda.monda  # noqa: F401
        from monda.utils import status as status_mod
        from monda.classes.workers import ENABLED_WORKERS
        from monda.classes.jobs import ENABLED_JOBS
        from monda.config_schema import JOB_SCHEMAS, WORKER_SCHEMAS
        import monda.classes.workers as workers_pkg
        import monda.classes.jobs as jobs_pkg
    except Exception as e:
        return [f"import failed: {e}"]

    for name in (
        "consume_config_reload",
        "mark_config_reload",
        "consume_pending_sleep",
    ):
        if not hasattr(status_mod, name):
            errors.append(f"monda.utils.status is missing '{name}' (mixed upgrade?)")

    missing_w = sorted(set(ENABLED_WORKERS) - set(WORKER_SCHEMAS))
    if missing_w:
        errors.append(f"workers without schema: {', '.join(missing_w)}")

    missing_j = sorted(set(ENABLED_JOBS) - set(JOB_SCHEMAS))
    if missing_j:
        errors.append(f"jobs without schema: {', '.join(missing_j)}")

    # Schema entries with no implementation are also a mixed-install smell.
    unused_w = sorted(set(WORKER_SCHEMAS) - set(ENABLED_WORKERS))
    if unused_w:
        errors.append(f"schemas without worker class: {', '.join(unused_w)}")
    unused_j = sorted(set(JOB_SCHEMAS) - set(ENABLED_JOBS))
    if unused_j:
        errors.append(f"schemas without job class: {', '.join(unused_j)}")

    workers_dir = Path(workers_pkg.__file__).resolve().parent
    for path in _orphan_modules(workers_dir, "W", set(ENABLED_WORKERS)):
        errors.append(
            f"orphan worker module left from an old install: {path} "
            f"(not in ENABLED_WORKERS)"
        )

    # Jobs live under jobs/hik/; check that package tree for J_*.py orphans.
    jobs_root = Path(jobs_pkg.__file__).resolve().parent
    job_py_files = list(jobs_root.rglob("J_*.py"))
    enabled_jobs = set(ENABLED_JOBS)
    for py in sorted(job_py_files):
        if py.stem not in enabled_jobs:
            errors.append(
                f"orphan job module left from an old install: {py} "
                f"(not in ENABLED_JOBS)"
            )

    # Spot-check that registered classes are importable under their names.
    for key, cls in ENABLED_WORKERS.items():
        if getattr(cls, "worker_class_name", None) != key:
            errors.append(
                f"worker '{key}' has worker_class_name="
                f"{getattr(cls, 'worker_class_name', None)!r}"
            )
    for key, cls in ENABLED_JOBS.items():
        if getattr(cls, "job_class_name", None) != key:
            errors.append(
                f"job '{key}' has job_class_name={getattr(cls, 'job_class_name', None)!r}"
            )

    # Ensure we are not somehow loading two different monda trees.
    monda_mod = importlib.import_module("monda")
    monda_root = Path(monda_mod.__file__).resolve().parent
    workers_root = Path(workers_pkg.__file__).resolve().parent
    if workers_root.parent.parent != monda_root:
        errors.append(
            f"workers package path {workers_root} is outside monda root {monda_root}"
        )

    return errors


def main() -> None:
    errors = verify()
    if errors:
        print("MonDa install verification FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print(
            "Re-run sudo ./install.sh from a clean checkout, or remove leftover "
            "files under the venv site-packages/monda tree.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("MonDa install verification OK.")


if __name__ == "__main__":
    main()
