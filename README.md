# MonDa — Monitoring Daemon

MonDa is a lightweight Python daemon that runs a configurable set of long-lived
**workers**, each performing one monitoring task (e.g. consuming a Hikvision
alert stream). Each worker runs in its own thread; the main loop watches them
and resurrects any that die.

## Installation (Linux)

```bash
sudo ./install.sh
```

The installer:

1. Checks for Python 3.10+ and `python3-venv`.
2. Creates a virtualenv at `/opt/monda/venv` and installs the package.
3. Symlinks the `monda` command to `/usr/local/bin/monda`.
4. Creates the config directory `/etc/monda/`.
5. Installs the `monda.service` systemd unit.
6. Creates `/var/log/monda/` and installs a logrotate config (daily rotation,
   30 days retained, gzip-compressed).

After installation:

```bash
# 1. Create config directory and add .ini files (see docs/config.md)
sudo mkdir -p /etc/monda
sudo nano /etc/monda/main.ini

# 2. Enable and start
sudo systemctl enable --now monda

# 3. Watch logs
journalctl -u monda -f
```

## Development (any platform)

```bash
# 1. Create venv and install (Python 3.10+)
python3 -m venv .venv
.venv/bin/pip install -e .          # Linux / macOS
# .venv\Scripts\pip install -e .    # Windows

# 2. Create config directory and .ini files (see docs/config.md)
mkdir config
# add config/main.ini (or any *.ini files)

# 3. Run
monda
```

Config directory is resolved in this order:

1. `CFG_DIR` environment variable, if set.
2. `./config/` (current working directory).
3. `/etc/monda/` (system-wide, Linux).

## How it works

1. `monda.py` registers signal handlers, loads the config, and applies the
   debug flag.
2. `validate_worker_config` checks for duplicate worker names across types.
3. `start_all_workers` instantiates every worker declared under
   `WORKER_CONFIG`, calls `initialize()` (which reads its slice of config),
   then `run()` (which spawns a daemon thread).
4. The main loop polls `Thread.is_alive()` for each worker every 5 seconds and
   re-creates any that have died.

Workers are decoupled from each other. The Hikvision pipeline uses a shared
bounded `deque` (`HikEvents`) so a producer worker can hand events to consumer
workers without tight coupling. When the consumer receives a VMD (motion
detection) event it automatically fires a `J_HikAlertSnap` job that grabs a
camera snapshot and sends it as an LED alert (rate-limited per camera).
Unknown event types are forwarded to LED as well.

## Documentation

- [docs/config.md](docs/config.md) — every config field, defaults, env vars.
- [docs/workers.md](docs/workers.md) — worker lifecycle, how to write a new one.
- [docs/jobs.md](docs/jobs.md) — Job base class for one-shot tasks.
- [docs/hik.md](docs/hik.md) — Hikvision producer + event model (optional subsystem).
- [docs/led.md](docs/led.md) — drop-folder alert integration with the `led` project.

## Project layout

```
install.sh                               # Linux installer (run as root)
monda.service                            # systemd unit template
monda/
  monda.py                               # entrypoint (main function)
  classes/
    base/
      Worker.py                          # abstract base worker (long-lived, threaded)
      Job.py                             # abstract base job (one-shot, fire-and-forget)
      Hik/HikEvent.py                    # Hikvision event model
    workers/
      __init__.py                        # ENABLED_WORKERS, deque, ignored-event helper
      worker_utils.py                    # start/validate helpers
      W_ConfigWatch.py                   # periodic config mtime check (auto-started)
      hik/
        W_HikProducer.py                 # consumes Hikvision alertStream → Redis
        W_HikConsumer.py                 # drains Redis → process_event
      telegram/
        W_TelegramBot.py                 # Telegram bot command dispatcher
    jobs/
      J_HikAlertSnap.py                  # Hikvision snapshot → LED alert job
  utils/
    logger.py                            # logging setup
    misc.py                              # config loader, splash, signals
    redis_client.py                      # process-wide Redis singleton
    led_alert.py                         # optional drop-folder alert integration
    globs.py                             # constants
```
