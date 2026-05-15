import json
from typing import cast

import redis as redis_lib

from monda.classes.base.Worker import Worker
from monda.classes.base.Hik.HikEvent import HikEvent
from monda.classes.jobs.J_HikAlertSnap import J_HikAlertSnap
from monda.classes.workers import HIK_EVENTS_TOPIC, is_ignored_event
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger
from monda.utils.misc import read_config
from monda.utils.redis_client import get_redis_client, reset_redis_client

logger = get_logger()

class W_HikConsumer(Worker):

    worker_class_name = "W_HikConsumer"
    worker_class_name_short = "W:HikCons"

    required_config_entries = []

    # Max events drained per _work tick. One LPOP returns up to this many in
    # a single round-trip; with Redis 6.2+ this is the main throughput knob.
    BATCH_SIZE = 500

    # videoloss - failed to write video data, losing video
    # VMD - motion detection
    known_event_types = ["videoloss", "VMD"]


    def __init__(self, name: str, interval_s: int):
        super().__init__(name, interval_s)

    def process_event(self, event: HikEvent) -> None:
        if is_ignored_event(event.name, event.state):
            return
        if event.name not in self.known_event_types:
            send_alert(f"Unknown Hik event: {event.name} ({event.state}) from {event.source}")
            return
        if event.name == "VMD":
            self._handle_vmd(event)

    def _handle_vmd(self, event: HikEvent) -> None:
        producer_cfg = (read_config()
                        .get("WORKER_CONFIG", {})
                        .get("W_HikProducer", {})
                        .get(event.source, {}))
        device_key = producer_cfg.get("DEVICE")
        if not device_key:
            logger.warning(f"No DEVICE config for producer '{event.source}', cannot snapshot.")
            return
        if not J_HikAlertSnap.acquire(device_key):
            return
        job = J_HikAlertSnap(event.source, {
            "HIK_DEVICE": device_key,
            "MESSAGE": f"Motion detected: {event.source}",
        })
        if job.initialize():
            job.run()

    def _initialize(self):
        # Validate REDIS section exists and is reachable enough to build a client.
        get_redis_client()
        return True

    def _work(self):
        # One round-trip: LPOP returns up to BATCH_SIZE entries as a list.
        # cast() narrows redis-py's Awaitable[T] | T stub union to T (sync client).
        try:
            batch = cast(list[str] | None, get_redis_client().lpop(HIK_EVENTS_TOPIC, self.BATCH_SIZE))
        except redis_lib.RedisError as e:
            reset_redis_client()
            logger.warning(f"Redis pop failed: {e}")
            return
        if not batch:
            return
        for raw in batch:
            try:
                event = HikEvent.from_dict(json.loads(raw))
            except Exception as e:
                logger.error(f"Dropping malformed event from Redis: {e}: {raw!r}")
                continue
            self.process_event(event)
            logger.debug(f"Consumed: {event!r}")
