# Configuration reference

MonDa reads a YAML config file at startup. The path is resolved in this order:

1. `CFGFILE_PATH` environment variable, if set.
2. `./config.yaml` (current working directory).
3. `/etc/monda/config.yaml` (system-wide, Linux).

If no config file is found in any of these locations, the program prints an
error and exits with code 1.

When installed via `install.sh`, the systemd unit sets
`CFGFILE_PATH=/etc/monda/config.yaml`.

The config file is a singleton: every `read_config()` call checks the file's
mtime and re-reads it only when the file has changed on disk. This means any
edit to `config.yaml` is picked up automatically — no restart required.
`write_config(data)` persists changes atomically (`.tmp` + `os.replace`)
and invalidates the cache so the next read sees the new content.

## Top-level fields

| Key             | Type   | Required | Default | Purpose                                                                  |
|-----------------|--------|----------|---------|--------------------------------------------------------------------------|
| `NAME`          | string | no       | —       | Display name. Currently informational only.                              |
| `DEBUG`         | int    | no       | `0`     | If truthy, enables `DEBUG`-level logging and prints the loaded config.   |
| `LOG_FILE`      | string | no       | —       | Path to a log file. If omitted, logs go to stdout only.                  |
| `TZ`            | string | no       | `"UTC"` | IANA timezone applied to parsed event timestamps (e.g. `Europe/Minsk`).  |
| `HIK_CONFIG`    | object | no       | —       | Hikvision subsystem settings. See below. Omit if you don't run Hik workers. |
| `REDIS`         | object | no       | —       | Single Redis endpoint. Required if any Hik worker is enabled. See below.   |
| `LED`           | object | no       | —       | Optional outbox integration. See below. Omit to fall back to stderr alerts. |
| `TELEGRAM`      | object | no       | —       | Telegram bot settings. See below. Omit if you don't run a Telegram worker. |
| `WORKER_CONFIG` | object | no       | `{}`    | Worker instances to start. See [workers.md](workers.md) for layout.      |
| `JOB_CONFIG`    | object | no       | `{}`    | Static job config. See [jobs.md](jobs.md) for layout and merge semantics. |
| `CONFIG_WATCH_INTERVAL` | int | no | `5`     | Seconds between config file mtime checks by the built-in config watcher. |

> On Windows, set `TZ` and ensure `tzdata` is installed in the venv —
> CPython's `zoneinfo` has no system database to fall back on. `pyproject.toml`
> already pins `tzdata` as a Windows-only dependency.

## `HIK_CONFIG` (optional)

The whole section is optional. Code paths that depend on it use `.get()`
defaults — MonDa starts and runs fine without any Hikvision workers.

| Key                    | Type   | Required          | Default | Purpose                                                          |
|------------------------|--------|-------------------|---------|------------------------------------------------------------------|
| `CREDENTIALS`          | object | if used by device  | `{}`    | Named credential entries referenced by `HIK_CONFIG.DEVICES.<NAME>.CREDENTIALS`. |
| `DEVICES`              | object | if running a Hik producer | `{}` | Named device entries. A `W_HikProducer` instance picks one by name via its `DEVICE` field. |
| `EVENT_DEQUE_MAX_SIZE` | int    | no                | `30`    | Cap on the shared `HikEvents` deque. Older events are dropped when full and a warning is logged. |
| `IGNORED_EVENTS`       | object | no                | `{}`    | Filter map: `{eventType: [eventState, ...]}`. Matching events are dropped *before* hitting Redis, and again on the consumer side. Empty state list = ignore every state of that event type. See [hik.md](hik.md). |

### `HIK_CONFIG.CREDENTIALS.<NAME>`

| Key        | Type   | Required | Purpose                          |
|------------|--------|----------|----------------------------------|
| `USERNAME` | string | yes      | HTTP Digest username for device. |
| `PASSWORD` | string | yes      | HTTP Digest password for device. |

A device references a credential entry by key via its own `CREDENTIALS` field.

### `HIK_CONFIG.DEVICES.<NAME>`

| Key           | Type   | Required | Default  | Purpose                                                |
|---------------|--------|----------|----------|--------------------------------------------------------|
| `ADDRESS`     | string | yes      | —        | Device IP or hostname.                                 |
| `CREDENTIALS` | string | yes      | —        | Name of an entry under `HIK_CONFIG.CREDENTIALS`.       |
| `PORT`        | string | no       | `"80"`   | Device port.                                           |
| `PROTOCOL`    | string | no       | `"http"` | `http` or `https`.                                     |

A `W_HikProducer` instance picks one device by name via its `DEVICE` field
(see [hik.md](hik.md)).

## `REDIS` (optional)

A single Redis endpoint shared by every worker that needs Redis. There is
exactly one process-wide client, built lazily on first use. If any push/pop
fails the client is dropped and rebuilt on the next call — so a transient
Redis outage doesn't leave workers stuck on a dead connection.

| Key        | Type   | Required | Default     | Purpose                                  |
|------------|--------|----------|-------------|------------------------------------------|
| `HOST`     | string | yes      | —           | Redis server host.                       |
| `PORT`     | int    | no       | `6379`      | Redis server port.                       |
| `DB`       | int    | no       | `0`         | Redis logical DB.                        |
| `USERNAME` | string | no       | —           | Username for Redis 6+ ACL.               |
| `PASSWORD` | string | no       | —           | Password.                                |

Socket timeouts default to 5 seconds.

The Hik subsystem uses a single Redis LIST keyed `hik_events` for the
producer→consumer pipeline. See [hik.md](hik.md) for details.

## `LED` (optional)

Drop-folder integration with the external `led` project. When configured,
`monda.utils.led_alert.send_alert(message, files)` writes a JSON descriptor
into `BASEDIR` for `led` to pick up. When omitted, the same call falls back
to stderr (and deletes any attached files instead of leaking them).

| Key       | Type   | Required | Default | Purpose                                            |
|-----------|--------|----------|---------|----------------------------------------------------|
| `BASEDIR` | string | yes      | —       | Directory `led` watches. Created if missing.       |

See [led.md](led.md) for the on-disk wire format and helper API.

## `TELEGRAM` (optional)

Telegram bot integration. When configured with a `W_TelegramBot` worker
instance, MonDa polls for incoming messages and dispatches commands.

| Key         | Type   | Required                    | Default | Purpose                                              |
|-------------|--------|-----------------------------|---------|------------------------------------------------------|
| `BOT_TOKEN` | string | if running a Telegram worker | —       | Telegram Bot API token from @BotFather.              |
| `CHAT_IDS`  | list   | if running a Telegram worker | `[]`    | List of integer chat IDs allowed to send commands.   |

Messages from chat IDs not in the list are silently ignored. Only messages
starting with `/` are treated as commands.

## `WORKER_CONFIG`

A dict keyed by **worker class name** (e.g. `W_HikProducer`). Each value is a
dict keyed by **instance name**. Instance names must be unique across all
worker types — `validate_worker_config` enforces this at startup.

Common per-instance fields recognised by the base `Worker`:

| Key        | Type | Required | Default | Purpose                                          |
|------------|------|----------|---------|--------------------------------------------------|
| `INTERVAL` | int  | no       | `10`    | Seconds between `_work()` invocations.           |

Per-worker-type fields are documented alongside each worker. For
`W_HikProducer` see [hik.md](hik.md).

## `JOB_CONFIG` (optional)

Same layout as `WORKER_CONFIG`: keyed by **job class name**, then by **instance
name**. Provides static defaults for jobs. At `initialize()` time, the static
config is merged with the runtime dict passed to the job's constructor —
runtime values win on key conflict.

A job type can be disabled entirely by setting `ENABLED: false` under its
class name. When disabled, `initialize()` returns `True` but `run()` silently
returns `None` — no thread is spawned, no error is logged. Enabled by default.
See [jobs.md](jobs.md) for details.

```yaml
JOB_CONFIG:
  J_HikAlertSnap:
    front_cam:
      HIK_DEVICE: cam_front
      CHANNEL: "101"
```

## Live reload

The config is a singleton with mtime-based caching. Every `read_config()`
call checks whether `config.yaml` has been modified on disk and re-reads it
only when necessary. Workers re-read their config slice before every
`_work()` tick, so edits to `config.yaml` take effect without a restart.

A built-in `W_ConfigWatch` worker is started automatically on every run. It
calls `read_config()` every `CONFIG_WATCH_INTERVAL` seconds (default `5`) to
keep the singleton fresh. No config entry is needed — it starts
unconditionally.

`write_config(data)` writes the full config atomically (`.tmp` +
`os.replace`) and invalidates the cache.

## Environment variables

| Variable        | Purpose                                                                |
|-----------------|------------------------------------------------------------------------|
| `CFGFILE_PATH`  | Override the config file location. Set by the systemd unit to `/etc/monda/config.yaml`. |
| `PSModulePath`  | Read by the terminal detector to apply Windows UTF-8 stdout fixes. Not user-set. |

## Example

```yaml
NAME: monda
DEBUG: 1
LOG_FILE: /var/log/monda.log
TZ: Europe/Minsk
CONFIG_WATCH_INTERVAL: 5

HIK_CONFIG:
  CREDENTIALS:
    DACHA:
      USERNAME: admin
      PASSWORD: secret
  DEVICES:
    reg_dacha:
      ADDRESS: 10.71.1.128
      CREDENTIALS: DACHA
      PORT: "80"
      PROTOCOL: http
  EVENT_DEQUE_MAX_SIZE: 30
  IGNORED_EVENTS:
    videoloss:
      - inactive

REDIS:
  HOST: 127.0.0.1
  PORT: 6379
  DB: 0
  USERNAME: default
  PASSWORD: redispass

LED:
  BASEDIR: /var/lib/led/inbox

TELEGRAM:
  BOT_TOKEN: "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
  CHAT_IDS:
    - 12345678
    - 87654321

WORKER_CONFIG:
  W_HikProducer:
    reg_dacha:
      DEVICE: reg_dacha
      INTERVAL: 5
  W_HikConsumer:
    main:
      INTERVAL: 3
  W_TelegramBot:
    main:
      INTERVAL: 5

JOB_CONFIG:
  J_HikAlertSnap:
    ENABLED: true
    ALERT_PERIOD: 15
    reg_dacha:
      HIK_DEVICE: reg_dacha
      CHANNEL: "101"
```

### What's optional vs. fatal

- **Hik unused.** Omit `HIK_CONFIG` and don't declare any `W_HikProducer`
  instances — MonDa starts and runs other workers normally.
- **Hik enabled but misconfigured.** If a `W_HikProducer` instance references
  a credential key that doesn't exist under `HIK_CONFIG.CREDENTIALS`, or if
  the credential entry is missing `USERNAME`/`PASSWORD`, initialization
  raises and the process exits. This is intentional — a configured-but-broken
  worker is a config bug, not a runtime condition.
- **No workers at all.** If `WORKER_CONFIG` is empty or absent, MonDa logs
  "FATAL: Could not start workers." and exits cleanly.
