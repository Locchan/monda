from monda.classes.jobs.hik.J_HikAlertSnap import J_HikAlertSnap
from monda.classes.jobs.hik.J_HikSnap import J_HikSnap
from monda.classes.jobs.hik.J_HikSnapArch import J_HikSnapArch

ENABLED_JOBS: dict[str, type] = {
    "J_HikAlertSnap": J_HikAlertSnap,
    "J_HikSnap": J_HikSnap,
    "J_HikSnapArch": J_HikSnapArch,
}

from monda.config_schema import JOB_SCHEMAS  # noqa: E402
_missing = [k for k in ENABLED_JOBS if k not in JOB_SCHEMAS]
if _missing:
    import sys
    print(f"FATAL: jobs without schema: {', '.join(_missing)}", file=sys.stderr)
    sys.exit(1)

