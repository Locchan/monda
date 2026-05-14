# Hikvision subsystem

An **optional** producer/consumer pipeline for Hikvision IP devices, backed by
a Redis LIST.

Nothing in this subsystem is required to run MonDa. If `HIK_CONFIG` is absent
and no `W_HikProducer`/`W_HikConsumer` instances appear under `WORKER_CONFIG`,
MonDa skips Hik entirely.

If a Hik worker *is* declared, its config must be valid: the referenced
credential key must exist under `HIK_CONFIG.CREDENTIALS` and have `USERNAME`
and `PASSWORD`, and the top-level `REDIS` section must have at least a `HOST`.
A broken reference raises during `_initialize` and crashes the process — by
design, since a misconfigured enabled worker is a bug, not a runtime
condition to absorb.

## Data flow

```
Hik device ──HTTP alertStream──▶ W_HikProducer ──RPUSH──▶ Redis LIST 'hik_events' ──LPOP──▶ W_HikConsumer ──▶ process_event()
                                       │                            ▲
                                       │  (Redis unreachable)       │
                                       ▼                            │
                                  local deque ───reconnect drain────┘
```

- The Redis key `hik_events` is the single shared topic. The constant is
  `HIK_EVENTS_TOPIC` in `monda/classes/workers/__init__.py`.
- `HIK_CONFIG.IGNORED_EVENTS` filters events at both ends: producers skip
  matching alerts before they hit the deque (saving Redis bandwidth) and
  consumers re-check so already-queued matches are also dropped. Format:
  `{eventType: [eventState, ...]}`; an empty state list ignores every state
  of that event type. The check lives in `is_ignored_event` in
  `monda/classes/workers/__init__.py`.
- All workers share **one process-wide Redis client**, built lazily in
  `monda/utils/redis_client.py`. Any push/pop failure calls
  `reset_redis_client()`, which drops the cached client so the next
  `get_redis_client()` call reconstructs it from config.
- Each producer has a local fallback: the module-level bounded `HikEvents`
  deque. New alerts are appended there, then the producer tries to drain to
  Redis. An event leaves the deque only after a successful `RPUSH`.
- On Redis outage the deque accumulates events up to `EVENT_DEQUE_MAX_SIZE`,
  then starts dropping the oldest (with a "bleeding data" log). When Redis
  recovers the next alert (and the start of every reconnect cycle) triggers a
  full drain.
- The consumer only reads from Redis. If Redis is unreachable, the tick is
  skipped and retried on the next `INTERVAL`. The local deque is producer-side
  only — consumers never see it.

## Components

| Piece                                | Role                                                                  |
|--------------------------------------|-----------------------------------------------------------------------|
| `W_HikProducer`                      | Worker. Connects to a device's `alertStream` and parses XML events into `HikEvent`s, appending them to the shared deque. |
| `W_HikConsumer`                      | Worker. Pops `HikEvent`s from the Redis LIST and dispatches them via `process_event` (stub). |
| `HikEvent`                           | Data class. One parsed alert: `name`, `state`, `date` (timezone-aware), `source`. |
| `HikEvents` (in `workers/__init__.py`) | Shared bounded `collections.deque` that producers append to and consumers drain. |
| `HIK_EVENT_DEQUE_MAX_SIZE`           | Resolved deque capacity. Producers compare against this before appending so they can log "queue is full — bleeding data" before silent drop. |

## `W_HikProducer` config

Each instance lives under `WORKER_CONFIG.W_HikProducer.<instance_name>`.

| Key        | Type   | Required | Default | Purpose                                                          |
|------------|--------|----------|---------|------------------------------------------------------------------|
| `DEVICE`   | string | yes      | —       | Name of an entry under `HIK_CONFIG.DEVICES`.                     |
| `INTERVAL` | int    | no       | `10`    | Seconds between reconnect attempts when the stream ends.         |

The referenced device entry in `HIK_CONFIG.DEVICES` provides `ADDRESS`,
`CREDENTIALS`, `PORT`, and `PROTOCOL` (see [config.md](config.md#hik_configdevicesname)).

The worker opens `<proto>://<ADDRESS>:<PORT>/ISAPI/Event/notification/alertStream`
with HTTP Digest auth and reads it as a long-lived multipart stream.

## How the parser works

`W_HikProducer._stream_alerts` is a generator over the response body. It looks
for `<EventNotificationAlert ...>` opening tags to start collecting lines and
yields the joined XML once it sees `</EventNotificationAlert>`. Boundary
markers and multipart headers are ignored implicitly because collection only
happens between those two tags.

`process_alert` parses each yielded XML chunk into a `HikEvent` via
`HikEvent.from_xml` and appends to `HikEvents`. If the deque is at capacity
*before* the append, a warning is logged — `deque.append` at `maxlen`
silently drops the oldest element, so this is the only chance to notice.

## `HikEvent`

Fields:

| Field    | XML source                          | Notes                                          |
|----------|-------------------------------------|------------------------------------------------|
| `name`   | `<eventType>`                       | e.g. `videoloss`, `IO`, `fielddetection`.      |
| `state`  | `<eventState>`                      | e.g. `active`, `inactive`.                     |
| `date`   | `<dateTime>` (ISO-8601)             | DVRs send naive timestamps → `TZ` from config is attached. Cameras send offset-aware timestamps (e.g. `+03:00`) → converted to `TZ`. Default `TZ` is `UTC`. |
| `source` | (not in payload)                    | Instance name of the `W_HikProducer` that produced the event. Passed in by `process_alert`. |

Construction logs the new event at `DEBUG` via `__repr__`.

## `W_HikConsumer`

Drains the Redis `hik_events` LIST. Each `_work` tick:

1. Issues one `LPOP hik_events BATCH_SIZE` (Redis 6.2+). The whole batch
   comes back in a single round-trip as a `list[str]`. `BATCH_SIZE` is a
   class constant (default `500`) — raise it for higher per-tick throughput.
2. Deserialises each JSON payload into a `HikEvent`. **Once popped, events
   are gone from Redis** — there is no requeue path. Pulling from the topic
   is the consumption.
3. Hands each to `process_event(event)`. The method's job is to act on the
   event; it has no return value and no failure mode that can put the event
   back. If you need at-least-once semantics with retries, do them inside
   `process_event` (or push to a downstream queue).
4. If Redis raises during `LPOP`, the tick is logged and skipped; the next
   `INTERVAL` retries. Malformed JSON in the topic is dropped with an error
   log.

Throughput tuning: per-tick capacity is `BATCH_SIZE` events; sustained rate
is `BATCH_SIZE / INTERVAL` events/sec. The default 500 + 1s gives 500 ev/s
on a single consumer, well above typical Hikvision event rates.

No required config beyond what `Worker` provides. `INTERVAL` controls poll
rate. The consumer uses the shared process-wide Redis client.

`process_event` filters via `known_event_types` and `is_ignored_event`.
Unknown event types are logged at WARNING and dropped.

**VMD handling:** when `process_event` receives a `VMD` (motion detection)
event, it resolves the source producer's `DEVICE` from `WORKER_CONFIG` and
fires a `J_HikAlertSnap` job — rate-limited to one snapshot per
`ALERT_PERIOD` seconds per camera (see [jobs.md](jobs.md#j_hikalertsnap)).

## Threading note

**Local deque** (`HikEvents`) is module-level shared mutable state across all
producers. `deque.append`/`appendleft`/`popleft` are atomic under CPython's
GIL, so the pop-send-or-restore drain pattern can only reorder events under a
race between two producers, never lose them. The "warn-then-append" check in
`process_alert` is not atomic — with multiple producers, the warning threshold
can race; harmless.

**Redis** is the cross-process source of truth. With multiple consumers
sharing one topic, `LPOP` is atomic so each event is delivered to exactly one
consumer. `LPOP` is destructive and there is no requeue path, so delivery is
at-most-once: an event lost while `process_event` is running (process crash,
unhandled exception inside the handler) is gone.

**Across producers/consumers and process restarts**: events buffered in a
producer's local deque are lost if the process dies before they reach Redis.
Once `RPUSH` succeeds, the event survives MonDa restarts as long as Redis
persistence is configured on the server side.
