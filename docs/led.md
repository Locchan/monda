# led integration

A thin, optional outbox helper that hands monitoring alerts to the external
`led` project by writing a JSON descriptor into a watched directory.

## Helper

```python
from monda.utils.led_alert import send_alert

send_alert("Camera 3 disconnected", target="general", files=["/tmp/cam3_snapshot.png"])
```

- `message` (str): the alert text.
- `target` (str, optional): key under `LED_TARGETS` in config (default `"general"`).
- `files` (list[str], optional): absolute paths to files that should travel
  with the alert. They will be **moved** (not copied) into the target's `BASEDIR`
  and referenced by name from the JSON.

The helper is fire-and-forget — no return value, no exceptions on the happy
path. Missing attachment paths are warned about and skipped; the alert is
still written.

## On-disk format

When a target's `BASEDIR` is configured, every call produces one JSON file in
that directory:

```
<BASEDIR>/alert_<YYYYMMDD_HHMMSS>_<8-hex-rand>.json
```

Contents:

```json
{
  "message": "Camera 3 disconnected",
  "files": ["cam3_snapshot.png"]
}
```

The `files` list contains names **relative to `BASEDIR`** so `led` can locate
them with `os.path.join(BASEDIR, name)` without worrying about original
paths. Filename collisions inside `BASEDIR` are resolved by appending a short
hex suffix to the moved file's stem.

## Atomicity

The JSON is written to `<final>.tmp` and then `os.replace`d to `<final>`.
On POSIX and on Windows (same-volume) this is atomic, so a watcher that
filters for `*.json` (and ignores `*.tmp`) will never see a half-written
descriptor. Attachments are moved before the JSON appears, so any file
referenced by a visible JSON is guaranteed to exist.

## Fallback when not configured

If the named target is absent from `LED_TARGETS` or its `BASEDIR` is not set:

- The message is printed to **stderr** as `Alert: <message>`.
- Any attached files are **deleted** (not retained) so callers that produce
  temporary files for an alert don't leak them when the integration is off.

This means callers can use `send_alert` unconditionally without checking
config — turning a target on or off is purely a config change.

## Configuration

See [config.md](config.md#led_targets-optional). Example:

```json
"LED_TARGETS": {
  "general":      { "BASEDIR": "/var/lib/led/general" },
  "dacha_alerts": { "BASEDIR": "/var/lib/led/dacha" }
}
```
