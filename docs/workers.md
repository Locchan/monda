# Workers

A **worker** is a single long-lived task running in its own daemon thread.
MonDa's job is to keep them alive: spawn them at startup, watch them, restart
any that die.

## Lifecycle

```
construct  →  initialize()  →  run()  →  _run() loop  →  (death)  →  resurrect
```

1. **Construct.** `start_worker_by_name` looks up the instance config in
   `WORKER_CONFIG`, finds the matching class in `ENABLED_WORKERS`, and
   instantiates it with `(name, interval)`.
2. **`initialize()`** (in `Worker`) loads the per-instance config slice from
   `WORKER_CONFIG[<class>][<name>]`, verifies `required_config_entries`, then
   calls the subclass hook `_initialize()`. Returns `False` on any problem —
   the worker won't start.
3. **`run()`** spawns a daemon thread named `<short_name>-<instance>` and
   returns it. The thread executes `_run()`.
4. **`_run()`** loops: call `_work()`, sleep `interval` seconds, repeat. Any
   exception is logged and ends the loop (the thread dies and the main loop
   resurrects it on the next health check).

## Required class attributes

| Attribute                  | Notes                                                     |
|----------------------------|-----------------------------------------------------------|
| `worker_class_name`        | Must equal the class name and must start with `W_`. Used as the key under `WORKER_CONFIG`. |
| `worker_class_name_short`  | Short tag used in thread names and log prefixes. No `-`.  |
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

## Naming rules

- Worker **class name** must start with `W_` and contain no `-`. Enforced in
  `Worker.__init__` (the process exits if violated).
- Worker **instance name** must contain no `-` and must be unique across all
  worker types (the resurrection logic parses it back out of the thread name).

## Resurrection

The main loop walks `worker_threads` every 5 seconds. If a thread isn't alive,
it calls `start_worker_by_name` with the instance name pulled out of the dead
thread's name. The new thread replaces the dead one in the list.
