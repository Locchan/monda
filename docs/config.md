# Configuration reference

MonDa reads a single JSON file. The path is resolved in this order:

1. `CFG_FILE` environment variable, if set.
2. `./config/config.json` (current working directory).
3. `/etc/monda/config.json` (system-wide, Linux).

If the file is not found, MonDa prints an error and exits with code 1.

When installed via `install.sh`, the systemd unit sets
`CFG_FILE=/etc/monda/config.json`.

The config is a singleton with mtime-based caching. Every `read_config()` call
compares the file's mtime and re-reads only if it changed. No restart required.

`write_config(data)` serialises the full config dict and writes it atomically
(`.tmp` + `os.replace`) back to the same file. `set_config_entry` and
`append_config_entry` read → patch → write the same file.

## CLI commands

### `monda`

Start the daemon. Reads config, acquires the PID file, starts all configured
workers, and enters the resurrection loop.

```
monda
```

Exits immediately with an error if another instance is already running (PID
file check). Responds to `SIGTERM` and `SIGINT` by releasing the PID file and
exiting cleanly.

### `monda status`

```
monda status
```

Reads the config, connects to the first `W_MondaStatus` instance's `PORT`,
fetches `GET /status`, and prints a human-readable summary with health
indicators:

```
🟢  monda v1.2.0 | uptime: 2h 3m 5s

Workers:
  🟢  W:Status_main               HTTP on port 7342.
  🟡  W:Docker_main               All containers healthy. [Restarted 3h ago, 1x]
  🔴  W:Systemd_main              Failed: myservice.service. [Crashed 5m ago: ...]

Jobs:
  🟢  J_HikAlertSnap/front_cam    Last run: success, took 2s. | Next: in 5m
  🔴  J_HikSnap/archive           Failed after 1s: connection refused. | Next: in 3m
```

Color semantics:
- 🟢 green — everything OK.
- 🟡 yellow — OK but the worker restarted within the last 24 h, or a
  monitored resource is in a warning state (overdue backup, failed service,
  unhealthy container).
- 🔴 red — the worker crashed, or the last job run failed.

The overall indicator on the header line reflects the worst color across all
workers and jobs.

Requires `W_MondaStatus` to be running. Exits with code 1 if the endpoint
is unreachable.

### `monda configure [config_path]`

```
monda configure
monda configure /etc/monda/config.json
```

Interactive wizard for creating or editing a config file. Loads the existing
file if it exists, presents a top-level menu, and saves on exit.

Menu sections:

| Section       | What it configures                                      |
|---------------|---------------------------------------------------------|
| General       | Top-level fields (`NAME`, `DEBUG`, `TZ`, `PID_FILE`, …) |
| LED Targets   | `LED_TARGETS` named outbox entries                      |
| Telegram      | `TELEGRAM` bot token and chat IDs                       |
| Hikvision     | `HIK_CONFIG` global settings, devices, and credentials  |
| Workers       | `WORKER_CONFIG` — add/edit/delete worker instances      |
| Jobs          | `JOB_CONFIG` — add/edit/delete job instances and toggle `ENABLED` |

Prompt format:
- `KEY [current]:` — empty input keeps the current or default value.
- `KEY (optional):` — empty input omits the key from the config entirely.
- Fields that accept a fixed set of values (e.g. `JOB_CLASS` in `W_Cron`)
  display a numbered list instead of a free-text prompt. Enter a number to
  select, or type the value directly. The current selection is marked with `◀`.

Config path is resolved the same way as the daemon: `CFG_FILE` env var →
`./config/config.json` → `/etc/monda/config.json`. Pass an explicit path as
the second argument to override. Changes are only written on "Save & Exit";
`Ctrl-C` discards without saving. The wizard exits with an error if the
current user does not have write permission for the resolved config path.

The wizard derives its field list, types, defaults, and descriptions from
`monda/config_schema.py`. Adding a schema entry for a new worker or job
makes it immediately available here. Fields with a `choices` callable show a
selection menu automatically.

## Top-level fields

| Key             | Type   | Required | Default | Purpose                                                                  |
|-----------------|--------|----------|---------|--------------------------------------------------------------------------|
| `NAME`          | string | no       | —       | Display name. Currently informational only.                              |
| `DEBUG`         | int    | no       | `0`     | If truthy, enables `DEBUG`-level logging and prints the loaded config.   |
| `LOG_FILE`      | string | no       | —       | Path to a log file. If omitted, logs go to stdout only.                  |
| `TZ`            | string | no       | `"UTC"` | IANA timezone applied to parsed event timestamps (e.g. `Europe/Minsk`).  |
| `HIK_CONFIG`    | object | no       | —       | Hikvision subsystem settings. See below.                                 |
| `REDIS`         | object | no       | —       | Single Redis endpoint. Required if any Hik worker is enabled.            |
| `LED_TARGETS`   | object | no       | —       | Named led outbox targets. See below.                                     |
| `TELEGRAM`      | object | no       | —       | Telegram bot settings. See below.                                        |
| `WORKER_CONFIG` | object | no       | `{}`    | Worker instances to start. See [workers.md](workers.md).                 |
| `JOB_CONFIG`    | object | no       | `{}`    | Static job config. See [jobs.md](jobs.md).                               |
| `CONFIG_WATCH_INTERVAL` | int | no | `5`   | Seconds between mtime checks by the built-in config watcher.            |

> On Windows, set `TZ` and ensure `tzdata` is installed in the venv —
> CPython's `zoneinfo` has no system database to fall back on. `pyproject.toml`
> already pins `tzdata` as a Windows-only dependency.

## `HIK_CONFIG` (optional)

| Key                    | Type   | Required          | Default | Purpose                                                          |
|------------------------|--------|-------------------|---------|------------------------------------------------------------------|
| `CREDENTIALS`          | object | if used by device | `{}`    | Named credential entries referenced by `HIK_CONFIG.DEVICES.<NAME>.CREDENTIALS`. |
| `DEVICES`              | object | if running a Hik producer | `{}` | Named device entries.                                       |
| `EVENT_DEQUE_MAX_SIZE` | int    | no                | `30`    | Cap on the shared `HikEvents` deque.                             |
| `IGNORED_EVENTS`       | object | no                | `{}`    | Filter map: `{eventType: [eventState, ...]}`. Empty list = ignore all states. |

### `HIK_CONFIG.CREDENTIALS.<NAME>`

| Key        | Type   | Required | Purpose                          |
|------------|--------|----------|----------------------------------|
| `USERNAME` | string | yes      | HTTP Digest username for device. |
| `PASSWORD` | string | yes      | HTTP Digest password for device. |

### `HIK_CONFIG.DEVICES.<NAME>`

| Key           | Type   | Required | Default  | Purpose                                          |
|---------------|--------|----------|----------|--------------------------------------------------|
| `ADDRESS`     | string | yes      | —        | Device IP or hostname.                           |
| `CREDENTIALS` | string | yes      | —        | Name of an entry under `HIK_CONFIG.CREDENTIALS`. |
| `PORT`        | string | no       | `"80"`   | Device port.                                     |
| `PROTOCOL`    | string | no       | `"http"` | `http` or `https`.                               |

## `REDIS` (optional)

| Key        | Type   | Required | Default | Purpose                    |
|------------|--------|----------|---------|----------------------------|
| `HOST`     | string | yes      | —       | Redis server host.         |
| `PORT`     | int    | no       | `6379`  | Redis server port.         |
| `DB`       | int    | no       | `0`     | Redis logical DB.          |
| `USERNAME` | string | no       | —       | Username for Redis 6+ ACL. |
| `PASSWORD` | string | no       | —       | Password.                  |

Socket timeouts default to 5 seconds. The Hik subsystem uses a Redis LIST
keyed `hik_events` for the producer→consumer pipeline. See [hik.md](hik.md).

## `LED_TARGETS` (optional)

A dict of named alert targets, each with a `BASEDIR` directory that the `led`
process watches. `send_alert` looks up the target by name. If the target is
missing or has no `BASEDIR`, alerts fall back to stderr.

```json
"LED_TARGETS": {
  "general":      { "BASEDIR": "/opt/led/messages/general" },
  "dacha_alerts": { "BASEDIR": "/opt/led/messages/dacha" }
}
```

| Key       | Type   | Required | Purpose                                      |
|-----------|--------|----------|----------------------------------------------|
| `BASEDIR` | string | yes      | Directory `led` watches. Created if missing. |

In code, pass the target name: `send_alert("msg", target="dacha_alerts", files=[...])`.
The default target is `"general"`. See [led.md](led.md) for the wire format.

## `TELEGRAM` (optional)

| Key         | Type   | Required                     | Purpose                                            |
|-------------|--------|------------------------------|----------------------------------------------------|
| `BOT_TOKEN` | string | if running a Telegram worker | Telegram Bot API token from @BotFather.            |
| `CHAT_IDS`  | list   | if running a Telegram worker | List of integer chat IDs allowed to send commands. |

## `WORKER_CONFIG`

Keyed by **worker class name**, then by **instance name**. Instance names must
be unique within their worker type.

| Key        | Type | Required | Default | Purpose                                |
|------------|------|----------|---------|----------------------------------------|
| `INTERVAL` | int  | no       | `10`    | Seconds between `_work()` invocations. |

## `JOB_CONFIG` (optional)

Same layout as `WORKER_CONFIG`. Provides static defaults merged with the
runtime dict at `initialize()` time — runtime values win on conflict.

Setting `ENABLED = false` under a job class name disables all instances of that
type silently. See [jobs.md](jobs.md).

## Live reload

A built-in `W_ConfigWatch` worker calls `read_config()` every
`CONFIG_WATCH_INTERVAL` seconds (default `5`). Workers re-read their config
slice before every `_work()` tick. Editing the file takes effect without a
restart, subject to the tick interval.

## Environment variables

| Variable      | Purpose                                                           |
|---------------|-------------------------------------------------------------------|
| `CFG_FILE`    | Path to the config file. Set by the systemd unit.                |
| `PSModulePath`| Read by the terminal detector for Windows UTF-8 fixes. Not user-set. |

## JSON format

Standard JSON. The config is a single object whose keys map directly to the
dict hierarchy. Values are natively typed: strings are quoted, integers and
booleans are unquoted, arrays use `[...]`.

## Example

```json
{
  "NAME": "monda",
  "DEBUG": 0,
  "LOG_FILE": "/var/log/monda.log",
  "TZ": "Europe/Minsk",
  "CONFIG_WATCH_INTERVAL": 5,
  "LED_TARGETS": {
    "general":      { "BASEDIR": "/var/lib/led/general" },
    "dacha_alerts": { "BASEDIR": "/var/lib/led/dacha" }
  },
  "HIK_CONFIG": {
    "EVENT_DEQUE_MAX_SIZE": 30,
    "IGNORED_EVENTS": { "videoloss": ["inactive"] },
    "CREDENTIALS": {
      "DACHA": { "USERNAME": "admin", "PASSWORD": "secret" }
    },
    "DEVICES": {
      "reg_dacha": { "ADDRESS": "10.71.1.128", "CREDENTIALS": "DACHA" }
    }
  },
  "REDIS": { "HOST": "127.0.0.1", "PORT": 6379, "DB": 0, "PASSWORD": "redispass" },
  "TELEGRAM": {
    "BOT_TOKEN": "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11",
    "CHAT_IDS": [12345678, 87654321]
  },
  "WORKER_CONFIG": {
    "W_HikProducer": { "reg_dacha": { "DEVICE": "reg_dacha", "INTERVAL": 5 } },
    "W_HikConsumer": { "main": { "INTERVAL": 3 } },
    "W_TelegramBot": { "main": { "INTERVAL": 5 } },
    "W_Cron": {
      "main": {
        "INTERVAL": 5,
        "JOBS": {
          "snap_reg_dacha": {
            "SCHEDULE": "*/5 * * * *",
            "JOB_CLASS": "J_HikSnap",
            "PARAMS": { "HIK_DEVICE": "reg_dacha", "DEST_DIR": "/var/lib/monda/snaps/reg_dacha", "CHANNEL": 101 }
          },
          "arch_reg_dacha": {
            "SCHEDULE": "0 * * * *",
            "JOB_CLASS": "J_HikSnapArch",
            "PARAMS": { "SRC_DIR": "/var/lib/monda/snaps/reg_dacha", "DEST_DIR": "/mnt/nfs/archive/reg_dacha" }
          }
        }
      }
    }
  },
  "JOB_CONFIG": {
    "J_HikAlertSnap": {
      "ENABLED": true,
      "ALERT_PERIOD": 15,
      "reg_dacha": { "HIK_DEVICE": "reg_dacha", "CHANNEL": 101 }
    }
  }
}
```

### What's optional vs. fatal

- **Hik unused.** Omit `HIK_CONFIG` entirely — MonDa starts and runs other workers normally.
- **Hik misconfigured.** Missing credentials or device fields cause an error at initialization — intentional.
- **No workers.** If `WORKER_CONFIG` is empty or absent, MonDa logs "FATAL: Could not start workers." and exits.
