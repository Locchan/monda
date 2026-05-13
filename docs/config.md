# Configuration reference

MonDa reads a single JSON file at startup. The path is resolved in this order:

1. `CFGFILE_PATH` environment variable, if set.
2. `./config.json` (current working directory).

If the file is missing, the program prints an error and exits with code 1.

The config is loaded **once** and cached in memory. `read_config(reload=True)`
forces a re-read; `write_config(data)` persists changes and reloads.

## Top-level fields

| Key             | Type   | Required | Default | Purpose                                                                  |
|-----------------|--------|----------|---------|--------------------------------------------------------------------------|
| `NAME`          | string | no       | —       | Display name. Currently informational only.                              |
| `DEBUG`         | int    | no       | `0`     | If truthy, enables `DEBUG`-level logging and prints the loaded config.   |
| `TZ`            | string | no       | `"UTC"` | IANA timezone applied to parsed event timestamps (e.g. `Europe/Minsk`).  |
| `HIK_CONFIG`    | object | no       | —       | Hikvision subsystem settings. See below. Omit if you don't run Hik workers. |
| `REDIS`         | object | no       | —       | Single Redis endpoint. Required if any Hik worker is enabled. See below.   |
| `WORKER_CONFIG` | object | no       | `{}`    | Worker instances to start. See [workers.md](workers.md) for layout.      |

> On Windows, set `TZ` and ensure `tzdata` is installed in the venv —
> CPython's `zoneinfo` has no system database to fall back on. `pyproject.toml`
> already pins `tzdata` as a Windows-only dependency.

## `HIK_CONFIG` (optional)

The whole section is optional. Code paths that depend on it use `.get()`
defaults — MonDa starts and runs fine without any Hikvision workers.

| Key                    | Type   | Required          | Default | Purpose                                                          |
|------------------------|--------|-------------------|---------|------------------------------------------------------------------|
| `CREDENTIALS`          | object | if used by worker | `{}`    | Named credential entries referenced by `WORKER_CONFIG` instances. |
| `EVENT_DEQUE_MAX_SIZE` | int    | no                | `30`    | Cap on the shared `HikEvents` deque. Older events are dropped when full and a warning is logged. |
| `IGNORED_EVENTS`       | object | no                | `{}`    | Filter map: `{eventType: [eventState, ...]}`. Matching events are dropped *before* hitting Redis, and again on the consumer side. Empty state list = ignore every state of that event type. See [hik.md](hik.md). |

### `HIK_CONFIG.CREDENTIALS.<NAME>`

| Key        | Type   | Required | Purpose                          |
|------------|--------|----------|----------------------------------|
| `USERNAME` | string | yes      | HTTP Digest username for device. |
| `PASSWORD` | string | yes      | HTTP Digest password for device. |

A worker references a credential entry by key via its own `CREDENTIALS` field.

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

## Environment variables

| Variable        | Purpose                                                                |
|-----------------|------------------------------------------------------------------------|
| `CFGFILE_PATH`  | Override the config file location.                                     |
| `PSModulePath`  | Read by the terminal detector to apply Windows UTF-8 stdout fixes. Not user-set. |

## Example

```json
{
  "NAME": "monda",
  "DEBUG": 1,
  "TZ": "Europe/Minsk",
  "HIK_CONFIG": {
    "CREDENTIALS": {
      "DACHA": { "USERNAME": "admin", "PASSWORD": "secret" }
    },
    "EVENT_DEQUE_MAX_SIZE": 30
  },
  "REDIS": {
    "HOST": "127.0.0.1",
    "PORT": 6379,
    "DB": 0
  },
  "WORKER_CONFIG": {
    "W_HikProducer": {
      "dacha": {
        "ADDRESS": "10.71.1.128",
        "PORT": "80",
        "CREDENTIALS": "DACHA",
        "INTERVAL": 5
      }
    },
    "W_HikConsumer": {
      "main": { "INTERVAL": 3 }
    }
  }
}
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
