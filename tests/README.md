# MonDa test suite

Separate from the `monda/` package. Creates its own venv, installs MonDa
editable, then runs pytest with heavy mocking (no real Telegram / Docker /
ZFS / Hik / SSH dependencies required at runtime).

## Run

```bash
./tests/run_tests.sh              # parallel by default (pytest-xdist -n auto)
./tests/run_tests.sh -n0          # serial (debugging)
./tests/run_tests.sh -k MDWatcher
./tests/run_tests.sh unit/
```

Tests share process-wide monda singletons, so parallelism uses **separate
processes** (xdist), not threads.

## Layout

| Path | Purpose |
|------|---------|
| `fixtures/configs/` | Fully fictional config shapes (`camera_site`, `lab_site`, `edge_site`) |
| `fixtures/samples/` | Captured/sanitized `mdstat`, `zpool status`, docker/systemd stubs |
| `unit/` | Abstractions: Worker, Job, status, schema, config reload, LED |
| `workers/` | Every `W_*` worker — positive and negative cases |
| `workers/test_worker_fail_fast.py` | Hard-budget checks: missing/inaccessible resources must return quickly (no hangs) |
| `jobs/` | Every `J_*` job — positive and negative cases |

## Maintenance

Any change to workers, jobs, or shared abstractions **must** update this suite
(add/adjust tests in the same change). See `.cursor/rules/update-tests.mdc`.
