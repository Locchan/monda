# Jobs

A **job** is a one-shot task that runs in its own daemon thread.
Fire-and-forget: callers (typically workers) get a `Thread` back from
`run()` and don't block. Use a Job for things like: ad-hoc cleanups,
scheduled batch operations, sending an alert from inside a hot path.

## Lifecycle

```
construct  →  initialize()  →  run() ──spawn thread──▶  _run()  →  _work()  →  (done | failed)
```

`run()` returns immediately. `_work()` executes in the spawned daemon thread.

Compared to `Worker`:

| Worker                                    | Job                                          |
|-------------------------------------------|----------------------------------------------|
| Long-lived loop in its own daemon thread. | One-shot, also in its own daemon thread. Fire-and-forget. |
| Config read from `WORKER_CONFIG`.         | Config from `JOB_CONFIG` + runtime dict, merged. |
| Resurrected by the main loop if the thread dies. | No resurrection. Failures are logged and the thread just exits. |
| `_work()` called repeatedly with `INTERVAL` sleeps. | `_work()` called once. Exceptions caught and logged. |

## Configuration

Jobs support two config sources, merged at `initialize()` time:

1. **Static config** from the config file under
   `JOB_CONFIG.<job_class_name>.<instance_name>` — same layout as
   `WORKER_CONFIG`. Good for settings that don't change between invocations
   (e.g. which device to use).
2. **Runtime config** passed into `__init__` as a dict. Good for per-invocation
   values (e.g. alert message). Overrides static entries on key conflict.

Either source is optional. A job can work purely from the config file, purely
from runtime config, or from both.

```json
"JOB_CONFIG": {
  "J_HikAlertSnap": {
    "front_cam": { "HIK_DEVICE": "cam_front", "CHANNEL": "101" }
  }
}
```

```python
job = J_HikAlertSnap("front_cam", {"MESSAGE": "Motion detected!"})
# effective config: {"HIK_DEVICE": "cam_front", "CHANNEL": "101", "MESSAGE": "Motion detected!"}
```

## Required class attributes

| Attribute                  | Notes                                                   |
|----------------------------|---------------------------------------------------------|
| `job_class_name`           | Must equal the class name and must start with `J_`.     |
| `job_class_name_short`     | Short tag for log prefixes. No `-`.                     |
| `required_config_entries`  | List of keys that must be present in the merged config. |

## Hooks to override

| Method          | Purpose                                                                       |
|-----------------|-------------------------------------------------------------------------------|
| `_initialize()` | One-time setup. Return `True` on success, `False` to abort the job.           |
| `_work()`       | The task body. Called once by `run()`. Raise to signal failure.               |

## What the base class logs

All lifecycle logs come from inside the job's own thread, so the threadName
column in the log identifies which job emitted them (e.g.
`J:Purge-nightly`).

- `Job '<name>' starting` — at INFO right before `_work()` runs. Wall-clock
  start is captured at the same moment for the duration measurement.
- `Job '<name>' finished in <duration>` — at INFO if `_work()` returns
  normally. Duration uses `time.monotonic()`, so wall-clock jumps don't
  perturb it. Format trims leading zero units: `30s`, `1m 30s`, `1h 1m 30s`.
- `Job '<name>' failed after <duration>: <exception>` — at ERROR with
  traceback if `_work()` raises any `Exception`, including the elapsed time
  before it failed. `BaseException` (e.g. `KeyboardInterrupt`, `SystemExit`)
  is not caught — those propagate inside the job thread.
- `Could not run job '<name>': not initialized` — at ERROR on the caller's
  thread if `run()` is called without a successful prior `initialize()`.
  `run()` returns `None` in this case.
- `Could not create job thread: <exception>` — at ERROR on the caller's
  thread if `Thread.start()` itself failed. `run()` returns `None`.
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

Run it (fire-and-forget):

```python
job = J_PurgeOldEvents("nightly", {"OLDER_THAN_DAYS": 30})
if job.initialize():
    job.run()  # returns Thread, caller doesn't block
```

If the caller needs to know when the job finishes (rare — Jobs are designed
for fire-and-forget), keep the returned Thread and `join()` it later. The
common path is to simply discard the return value.

## `J_HikAlertSnap`

Grabs a snapshot from a Hikvision camera and sends it as an LED alert.

| Key          | Type   | Required | Default | Source  | Purpose                                             |
|--------------|--------|----------|---------|---------|-----------------------------------------------------|
| `HIK_DEVICE` | string | yes      | —       | either  | Name of an entry under `HIK_CONFIG.DEVICES`.        |
| `MESSAGE`    | string | yes      | —       | runtime | Alert text forwarded to the LED integration.        |
| `CHANNEL`    | string | no       | `"101"` | either  | ISAPI streaming channel (101 = camera 1 main stream). |

Snapshot endpoint: `<proto>://<address>:<port>/ISAPI/Streaming/channels/<CHANNEL>/picture`
with HTTP Digest auth from the device's credentials.

The snapshot is saved as a temporary `.jpg`, then handed to `send_alert`
which moves it into `LED.BASEDIR` and writes the LED-format JSON descriptor.

### Rate limiting

`J_HikAlertSnap` can fire at most once per `ALERT_PERIOD` seconds per camera.
The period is read from `JOB_CONFIG.J_HikAlertSnap.ALERT_PERIOD` (default
`15`). Callers must check `J_HikAlertSnap.acquire(device_key)` before creating
the job — it returns `True` and marks the timestamp atomically if the cooldown
has expired, `False` otherwise.

`W_HikConsumer` calls `acquire()` automatically when it receives a VMD event.

### Usage

`W_HikConsumer` fires this job automatically on VMD (motion detection) events.
Manual usage:

```python
from monda.classes.jobs.J_HikAlertSnap import J_HikAlertSnap

if J_HikAlertSnap.acquire("cam_front"):
    job = J_HikAlertSnap("front_cam", {"HIK_DEVICE": "cam_front", "MESSAGE": "Motion"})
    if job.initialize():
        job.run()
```

## Naming rules

- Class name must start with `J_` and contain no `-`. Enforced in
  `Job.__init__` (process exits if violated).
- Job instance name must contain no `-`.
