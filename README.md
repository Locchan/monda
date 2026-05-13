# MonDa — Monitoring Daemon

MonDa is a lightweight Python daemon that runs a configurable set of long-lived
**workers**, each performing one monitoring task (e.g. consuming a Hikvision
alert stream). Each worker runs in its own thread; the main loop watches them
and resurrects any that die.

## Quickstart

```powershell
# 1. Create venv and install (Python 3.12+)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

# 2. Edit config.json (see docs/config.md)

# 3. Run
.\.venv\Scripts\python.exe main.py
```

By default the config is read from `./config.json`. Override with the
`CFGFILE_PATH` environment variable.

## How it works

1. `main.py` loads the config and applies the debug flag.
2. `validate_worker_config` checks for duplicate worker names across types.
3. `start_all_workers` instantiates every worker declared under
   `WORKER_CONFIG`, calls `initialize()` (which reads its slice of config),
   then `run()` (which spawns a daemon thread).
4. The main loop polls `Thread.is_alive()` for each worker every 5 seconds and
   re-creates any that have died.

Workers are decoupled from each other. The Hikvision pipeline uses a shared
bounded `deque` (`HikEvents`) so a producer worker can hand events to future
consumer workers without tight coupling.

## Documentation

- [docs/config.md](docs/config.md) — every config field, defaults, env vars.
- [docs/workers.md](docs/workers.md) — worker lifecycle, how to write a new one.
- [docs/hik.md](docs/hik.md) — Hikvision producer + event model (optional subsystem).

## Project layout

```
main.py                                  # entrypoint
config.json                              # runtime config
monda/
  classes/
    base/
      Worker.py                          # abstract base worker
      Hik/HikEvent.py                    # Hikvision event model
    workers/
      __init__.py                        # ENABLED_WORKERS, shared HikEvents deque
      W_HikProducer.py                   # consumes Hikvision alertStream
      worker_utils.py                    # start/validate helpers
  utils/
    logger.py                            # logging setup
    misc.py                              # config loader, splash, signals
    globs.py                             # constants
```
