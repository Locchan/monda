# Workers

A **worker** is a single long-lived task running in its own daemon thread.
MonDa's job is to keep them alive: spawn them at startup, watch them, restart
any that die.

## Lifecycle

```
construct  →  initialize()  →  run()  →  _run() loop  →  (death)  →  resurrect
```

1. **Construct.** `start_worker_by_name(worker_type, instance_name)` looks up
   the instance config in `WORKER_CONFIG`, finds the matching class in
   `ENABLED_WORKERS`, and instantiates it with `(instance_name, interval)`.
2. **`initialize()`** (in `Worker`) loads the per-instance config slice from
   `WORKER_CONFIG[<class>][<instance_name>]`, verifies `required_config_entries`,
   then calls the subclass hook `_initialize()`. Returns `False` on any problem —
   the worker won't start.
3. **`run()`** spawns a daemon thread named `<short_name>_<instance>` (the
   worker's `self.name`) and returns it. The thread executes `_run()`.
4. **`_run()`** loops: call `_refresh_config()`, call `_work()`, sleep
   `interval` seconds, repeat. Any `BaseException` is caught, logged, and ends
   the loop (the thread dies and the main loop resurrects it on the next health
   check).

## Required class attributes

| Attribute                  | Notes                                                     |
|----------------------------|-----------------------------------------------------------|
| `worker_class_name`        | Must equal the class name and must start with `W_`. Used as the key under `WORKER_CONFIG`. |
| `worker_class_name_short`  | Short tag prepended to the instance name to form `self.name` (e.g. `W:Cron_main`). No `-`. |
| `required_config_entries`  | List of keys that must be present in the instance config. |

## Hooks to override

| Method          | Purpose                                                                |
|-----------------|------------------------------------------------------------------------|
| `_initialize()` | One-time setup: build URLs, resolve credentials, open files. Return `True` on success, `False` to abort the worker. |
| `_work()`       | The task body. Called repeatedly with `INTERVAL` seconds in between.   |

## Writing a new worker

1. Create `monda/classes/workers/W_MyThing.py`:

   ```python
   from monda.classes.base.Worker import Worker

   class W_MyThing(Worker):
       worker_class_name = "W_MyThing"
       worker_class_name_short = "W:MyThing"
       required_config_entries = ["FOO"]

       def _initialize(self):
           self.foo = self.config["FOO"]
           return True

       def _work(self):
           # one iteration of the task
           ...
   ```

2. Register it in `monda/classes/workers/__init__.py`:

   ```python
   from monda.classes.workers.W_MyThing import W_MyThing

   ENABLED_WORKERS = {
       "W_HikProducer": W_HikProducer,
       "W_MyThing": W_MyThing,
   }
   ```

3. Add an instance to `config.json`:

   ```json
   "WORKER_CONFIG": {
     "W_MyThing": {
       "my_instance": { "FOO": "bar", "INTERVAL": 30 }
     }
   }
   ```

## W_Cron

Runs jobs on crontab schedules. Every tick (recommended `INTERVAL: 5`) it
checks each configured job and fires it if at least one schedule slot occurred
since the last tick finished — at most once per job per tick, regardless of
how many slots were missed (no replay of accumulated backlog).

If multiple jobs are due in the same tick they all fire: the loop spawns each
as a daemon thread via `job.run()` and moves on immediately, so execution is
concurrent even though the scheduling check is sequential.

### Config

```json
"WORKER_CONFIG": {
  "W_Cron": {
    "main": {
      "INTERVAL": 5,
      "JOBS": {
        "<job_instance_name>": {
          "SCHEDULE": "* * * * *",
          "JOB_CLASS": "J_SomeJob",
          "SILENT": false,
          "PARAMS": { "KEY": "value" }
        }
      }
    }
  }
}
```

`SCHEDULE` uses standard five-field crontab syntax (`min hour dom month dow`).
`PARAMS` is merged as the runtime config override passed to the job constructor
— it wins over any static `JOB_CONFIG` values on key conflict.

To add a new job class to the scheduler, register it in
`monda/classes/jobs/__init__.py` under `ENABLED_JOBS`.

## Naming rules

- Worker **class name** must start with `W_` and contain no `-`. Enforced in
  `Worker.__init__` (the process exits if violated).
- Worker **instance name** must contain no `-` and must be unique within its
  worker type. The same instance name may be reused across different types
  (e.g. both `W_Cron` and `W_ConfigWatch` can have an instance named `main`).
- `self.name` is set automatically to `f"{worker_class_name_short}_{instance_name}"`
  and is used as the thread name and in log messages. Subclasses must not
  set `self.name` manually.

## W_TelegramBot

Polls for Telegram messages and dispatches bot commands. Requires the
`TELEGRAM` section in `config.json` (see [config.md](config.md)).

### Commands

| Command        | Description                                    |
|----------------|------------------------------------------------|
| `/hik_sender`  | Toggle `J_HikAlertSnap` on or off (no arguments). |
| `/help`        | List all available commands.                   |

Only messages from chat IDs listed in `TELEGRAM.CHAT_IDS` are processed.
Messages not starting with `/` are silently ignored.

### Config

```json
"WORKER_CONFIG": {
  "W_TelegramBot": {
    "main": { "INTERVAL": 2 }
  }
}
```

## W_MondaStatus

Starts a minimal HTTP server that responds to `GET /status` with a JSON
object describing the daemon's internal state. All other paths return 404.

The server runs in its own daemon thread started in `_initialize`. The
worker's `_work` tick only checks whether that thread is alive and restarts
it if not. `INTERVAL` controls how often the health check runs, not the
request rate.

### `monda status` command

```
monda status
```

Reads the config, looks up the first `W_MondaStatus` instance's `PORT`,
sends `GET /status`, and prints a human-readable summary:

```
status:  ok
version: 1.1.31+m
uptime:  0h 5m 12s
```

### Single-instance enforcement

MonDa writes its PID to a file on startup (`/tmp/monda.pid` by default, or
the `PID_FILE` top-level config key). If the file exists and the recorded
process is still alive, the new instance exits immediately with an error.
The PID file is removed on clean shutdown (SIGTERM / SIGINT) and on normal
Python exit via `atexit`.

### Config

| Key        | Type | Required | Default | Purpose                             |
|------------|------|----------|---------|-------------------------------------|
| `PORT`     | int  | yes      | —       | TCP port for the HTTP status server.|
| `INTERVAL` | int  | no       | `10`    | Seconds between server health checks.|

Top-level config key (not under `WORKER_CONFIG`):

| Key        | Type   | Required | Default          | Purpose             |
|------------|--------|----------|------------------|---------------------|
| `PID_FILE` | string | no       | `/tmp/monda.pid` | Path to the PID file.|

```json
"WORKER_CONFIG": {
  "W_MondaStatus": {
    "main": { "PORT": 7342, "INTERVAL": 30 }
  }
}
```

### Response format (stub)

```json
{
  "status": "ok",
  "version": "1.1.31+m",
  "uptime_seconds": 312.4
}
```

## W_BackupWatcherRaw

Checks a set of named directories (including subdirectories) for recent files.
On every tick it finds the newest file mtime in each tree. If that mtime is
older than `now - (EXPECTED_PERIOD_MINUTES + PERMITTED_LAG_MINUTES) * 60`, or
if the directory contains no files at all, a `send_alert` is fired with the
backup name and the timestamp of the last file found.

Alerts are deduplicated per backup: at most one alert is sent per 24 hours for
a given backup entry. The cooldown resets as soon as the backup recovers, so
a subsequent failure alerts immediately.

### Config

| Key            | Type   | Required | Default     | Purpose                                                        |
|----------------|--------|----------|-------------|----------------------------------------------------------------|
| `BACKUPS`      | object | yes      | —           | Dict of named backup entries (see below).                      |
| `ALERT_TARGET` | string | no       | `"general"` | LED target name passed to `send_alert`.                        |
| `INTERVAL`     | int    | no       | `10`        | Seconds between checks. Set to e.g. `3600` for hourly checks. |

Each entry under `BACKUPS`:

| Key                      | Type   | Required | Purpose                                    |
|--------------------------|--------|----------|--------------------------------------------|
| `PATH`                   | string | yes      | Root directory to scan (recursively).      |
| `EXPECTED_PERIOD_MINUTES`| int    | yes      | How often a fresh backup is expected.      |
| `PERMITTED_LAG_MINUTES`  | int    | yes      | Grace period added on top of the period.   |

```json
"WORKER_CONFIG": {
  "W_BackupWatcherRaw": {
    "main": {
      "INTERVAL": 3600,
      "ALERT_TARGET": "general",
      "BACKUPS": {
        "photos": {
          "PATH": "/mnt/backup/photos",
          "EXPECTED_PERIOD_MINUTES": 1440,
          "PERMITTED_LAG_MINUTES": 120
        }
      }
    }
  }
}
```

## W_BackupWatcherBorg

Checks a set of named Borg repositories for recent archives. On every tick it
runs `borg list --last 1 --json <path>` for each repo and reads the `start`
timestamp of the latest archive. If that timestamp is older than
`now - (EXPECTED_PERIOD_MINUTES + PERMITTED_LAG_MINUTES) * 60`, or if there
are no archives at all, a `send_alert` is fired. If `borg list` fails (non-zero
exit), an alert is also sent with the error output.

Alerts are deduplicated per backup: at most one alert is sent per 24 hours for
a given backup entry. The cooldown resets as soon as the backup recovers, so
a subsequent failure alerts immediately.

Borg is invoked as a subprocess. The `borg` binary must be on `PATH`.

### Config

| Key            | Type   | Required | Default     | Purpose                                                        |
|----------------|--------|----------|-------------|----------------------------------------------------------------|
| `BACKUPS`      | object | yes      | —           | Dict of named repository entries (see below).                  |
| `ALERT_TARGET` | string | no       | `"general"` | LED target name passed to `send_alert`.                        |
| `INTERVAL`     | int    | no       | `10`        | Seconds between checks.                                        |

Each entry under `BACKUPS`:

| Key                      | Type   | Required | Purpose                                           |
|--------------------------|--------|----------|---------------------------------------------------|
| `PATH`                   | string | yes      | Path to the Borg repository.                      |
| `EXPECTED_PERIOD_MINUTES`| int    | yes      | How often a fresh backup is expected.             |
| `PERMITTED_LAG_MINUTES`  | int    | yes      | Grace period added on top of the period.          |
| `PASSPHRASE`             | string | no       | Borg repo passphrase (`BORG_PASSPHRASE` env var). |

```json
"WORKER_CONFIG": {
  "W_BackupWatcherBorg": {
    "main": {
      "INTERVAL": 3600,
      "BACKUPS": {
        "dacha_borg": {
          "PATH": "/mnt/backup/borg/dacha",
          "EXPECTED_PERIOD_MINUTES": 1440,
          "PERMITTED_LAG_MINUTES": 120,
          "PASSPHRASE": "secret"
        }
      }
    }
  }
}
```

## W_SSHLoginWatcher

Fires a `send_alert` for every successful SSH login. No deduplication —
each login is a discrete security event.

### Source detection

The worker resolves its event source at `_initialize` time in this order:

1. **`LOG_PATH` config key** — use the specified file directly.
2. **Auto-detect** — try these paths in order, use the first readable one:
   - `/var/log/audit/audit.log` (auditd — RHEL/Fedora)
   - `/var/log/auth.log` (rsyslog — Debian/Ubuntu)
   - `/var/log/secure` (rsyslog — RHEL alternative)
3. **journalctl fallback** — if no readable file is found, query
   `journalctl -u ssh -u sshd` (covers both Debian's `ssh.service` and
   `sshd.service` on other distros).

### File mode

Tracks the file by inode + offset. On startup the worker seeks to the current
end so historical entries do not generate alerts. Log rotation (inode change)
and truncation (size < position) are detected and reset the read position.

Two line parsers are used automatically:
- **audit format** (path contains `audit`): parses `type=USER_LOGIN` lines
  with `res=success` and `sshd` in the exe; extracts `acct=` (with hex
  decode) and `addr=`.
- **syslog format** (`auth.log`, `secure`): matches
  `sshd[N]: Accepted <method> for <user> from <addr>`.

### journalctl mode

Uses `--cursor-file` to track read position across ticks and process
restarts. The cursor file is written to the system temp directory as
`monda_ssh_cursor_<instance_name>`. On first run the cursor is initialised
to the current journal end so old events are not replayed. If `journalctl`
is unavailable or fails, `_initialize` returns `False` and the worker does
not start.

### Config

| Key            | Type   | Required | Default     | Purpose                                      |
|----------------|--------|----------|-------------|----------------------------------------------|
| `LOG_PATH`     | string | no       | auto-detect | Explicit path to a log file. Skips detection.|
| `ALERT_TARGET` | string | no       | `"general"` | LED target name passed to `send_alert`.      |
| `INTERVAL`     | int    | no       | `10`        | Seconds between reads.                       |

```json
"WORKER_CONFIG": {
  "W_SSHLoginWatcher": {
    "main": {
      "INTERVAL": 10,
      "ALERT_TARGET": "general"
    }
  }
}
```

## W_SystemdWatcher

Queries `systemctl` for failed services on every tick and fires a
`send_alert` for each one found. Alerts are deduplicated per service name:
at most one alert per 24 hours. The cooldown for a service is cleared as soon
as it leaves the failed state, so a subsequent failure alerts immediately.

`systemctl` is invoked as a subprocess and must be available on `PATH`.

### Config

| Key            | Type        | Required | Default     | Purpose                                   |
|----------------|-------------|----------|-------------|-------------------------------------------|
| `ALERT_TARGET` | string      | no       | `"general"` | LED target name passed to `send_alert`.   |
| `IGNORE`       | list[string]| no       | `[]`        | Service unit names to exclude from alerts.|
| `INTERVAL`     | int         | no       | `10`        | Seconds between checks.                   |

```json
"WORKER_CONFIG": {
  "W_SystemdWatcher": {
    "main": {
      "INTERVAL": 60,
      "ALERT_TARGET": "general",
      "IGNORE": ["user@1000.service"]
    }
  }
}
```

## W_DockerWatcher

Queries `docker ps -a` on every tick and fires a `send_alert` for each
container whose state is `exited` or `dead`. Alerts are deduplicated per
container name: at most one alert per 24 hours. The cooldown for a container
is cleared as soon as it leaves an alerting state.

`docker` is invoked as a subprocess and must be available on `PATH`. The
process user must have permission to query the Docker daemon.

### Config

| Key            | Type        | Required | Default     | Purpose                                        |
|----------------|-------------|----------|-------------|------------------------------------------------|
| `ALERT_TARGET` | string      | no       | `"general"` | LED target name passed to `send_alert`.        |
| `IGNORE`       | list[string]| no       | `[]`        | Container names to exclude from alerts.        |
| `INTERVAL`     | int         | no       | `10`        | Seconds between checks.                        |

```json
"WORKER_CONFIG": {
  "W_DockerWatcher": {
    "main": {
      "INTERVAL": 60,
      "ALERT_TARGET": "general",
      "IGNORE": ["init-container", "one-shot-task"]
    }
  }
}
```

## Resurrection

The main loop tracks a list of `(thread, worker_type, instance_name)` tuples.
Every 5 seconds it checks each thread with `is_alive()`. If a thread has died
it calls `start_worker_by_name(worker_type, instance_name)` — the type and
instance name are stored in the tuple, so no thread-name parsing is involved.
The new thread replaces the dead one in the list.
