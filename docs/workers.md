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

## Resurrection

The main loop tracks a list of `(thread, worker_type, instance_name)` tuples.
Every 5 seconds it checks each thread with `is_alive()`. If a thread has died
it calls `start_worker_by_name(worker_type, instance_name)` — the type and
instance name are stored in the tuple, so no thread-name parsing is involved.
The new thread replaces the dead one in the list.
