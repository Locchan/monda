from monda.classes.jobs.hik.J_HikAlertSnap import J_HikAlertSnap
from monda.classes.jobs.hik.J_HikSnap import J_HikSnap
from monda.classes.jobs.hik.J_HikSnapArch import J_HikSnapArch

ENABLED_JOBS: dict[str, type] = {
    "J_HikAlertSnap": J_HikAlertSnap,
    "J_HikSnap": J_HikSnap,
    "J_HikSnapArch": J_HikSnapArch,
}
