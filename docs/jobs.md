# Jobs

A **job** is a one-shot task. Same shape as a [Worker](workers.md), but it
runs once instead of looping forever in a thread. Use a Job for things like:
ad-hoc cleanups, scheduled batch operations, on-demand actions triggered by
a worker or external event.

## Lifecycle

```
construct  →  initialize()  →  run()  →  (done | failed)
```

Compared to `Worker`:

| Worker                                    | Job                                          |
|-------------------------------------------|----------------------------------------------|
| Long-lived loop in its own daemon thread. | Synchronous one-shot. Caller blocks on it.   |
| Config read from `WORKER_CONFIG`.         | Config passed into `__init__` as a dict.     |
| Resurrected by `main.py` if the thread dies. | No resurrection. Caller decides what to do on failure. |
| `_work()` called repeatedly with `INTERVAL` sleeps. | `_work()` called once, exceptions caught and logged. |

## Required class attributes

| Attribute                  | Notes                                                   |
|----------------------------|---------------------------------------------------------|
| `job_class_name`           | Must equal the class name and must start with `J_`.     |
| `job_class_name_short`     | Short tag for log prefixes. No `-`.                     |
| `required_config_entries`  | List of keys that must be present in `job_config`.      |

## Hooks to override

| Method          | Purpose                                                                       |
|-----------------|-------------------------------------------------------------------------------|
| `_initialize()` | One-time setup. Return `True` on success, `False` to abort the job.           |
| `_work()`       | The task body. Called once by `run()`. Raise to signal failure.               |

## What the base class logs

- `Job '<name>' starting` — at INFO right before `_work()` runs.
- `Job '<name>' finished` — at INFO if `_work()` returns normally.
- `Job '<name>' failed: <exception>` — at ERROR with traceback if `_work()`
  raises any `Exception`. `BaseException` (e.g. `KeyboardInterrupt`,
  `SystemExit`) is not caught — those propagate.
- `Could not run job '<name>': not initialized` — at ERROR if `run()` is
  called without a successful prior `initialize()`.
- `Could not initialize: missing the following config entries: [...]` — at
  ERROR if `initialize()` finds missing required fields.

## Writing a new job

```python
from monda.classes.base.Job import Job

class J_PurgeOldEvents(Job):
    job_class_name = "J_PurgeOldEvents"
    job_class_name_short = "J:Purge"
    required_config_entries = ["OLDER_THAN_DAYS"]

    def _initialize(self):
        self.cutoff_days = int(self.config["OLDER_THAN_DAYS"])
        return True

    def _work(self):
        # do the actual purge; raise on failure
        ...
```

Run it:

```python
job = J_PurgeOldEvents("nightly", {"OLDER_THAN_DAYS": 30})
if job.initialize():
    job.run()
```

## Naming rules

- Class name must start with `J_` and contain no `-`. Enforced in
  `Job.__init__` (process exits if violated).
- Job instance name must contain no `-`.
