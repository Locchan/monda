import json

import redis as redis_lib
import requests
from requests.auth import HTTPDigestAuth

from monda.classes.base.Worker import Worker
from monda.classes.base.Hik.HikEvent import HikEvent
from monda.classes.workers import HikEvents, HIK_EVENTS_TOPIC, is_ignored_event
from monda.utils.logger import get_logger
from monda.utils.misc import read_config
from monda.utils.redis_client import get_redis_client, reset_redis_client

logger = get_logger()

class W_HikProducer(Worker):

    alerts_buffer = []

    worker_class_name = "W_HikProducer"
    worker_class_name_short = "W:HikProd"

    required_config_entries = ["DEVICE"]

    def __init__(self, name: str, interval_s: int):
        super().__init__(name, interval_s)
        self.auth = None
        self.alert_url = None

    def process_alert(self, alert: str):
        event = HikEvent.from_xml(alert, source=self.name)
        if is_ignored_event(event.name, event.state):
            return
        config = read_config()
        max_size = config.get("HIK_CONFIG", {}).get("EVENT_DEQUE_MAX_SIZE", 30)
        if len(HikEvents) > (max_size / 2):
            logger.warn(f"HikEvent queue is more than half-full ({max_size}).")
        elif len(HikEvents) == max_size:
            logger.error(f"HikEvent queue is full ({max_size}). We're bleeding data!")
        HikEvents.append(event)
        self._drain_to_redis()

    def _drain_to_redis(self):
        # Pop-then-send-or-restore: each deque op is atomic, so a race with
        # another producer can only reorder events, never lose them.
        while HikEvents:
            try:
                event = HikEvents.popleft()
            except IndexError:
                return
            try:
                get_redis_client().rpush(HIK_EVENTS_TOPIC, json.dumps(event.to_dict()))
            except redis_lib.RedisError as e:
                HikEvents.appendleft(event)
                reset_redis_client()
                logger.warning(f"Redis push failed, kept in local queue ({len(HikEvents)} pending): {e}")
                return

    def _stream_alerts(self):
        with requests.get(self.alert_url, auth=self.auth, stream=True, timeout=None) as response:
            if response.status_code != 200:
                logger.warning(f"Could not connect to alert stream ({self.alert_url}): {response.status_code}")
                return
            logger.info("Connected to alert stream.")

            buffer = []
            for raw in response.iter_lines():
                if not raw:
                    continue
                line = raw.decode('utf-8')

                if line.startswith("<EventNotificationAlert"):
                    buffer = [line]
                elif buffer:
                    buffer.append(line)
                    if line.startswith("</EventNotificationAlert>"):
                        yield "\n".join(buffer)
                        buffer = []


    def _initialize(self):
        hik_config = read_config().get("HIK_CONFIG", {})

        device_key = self.config["DEVICE"]
        devices = hik_config.get("DEVICES", {})
        if device_key not in devices:
            raise RuntimeError(f"Device '{device_key}' not found in HIK_CONFIG.DEVICES.")
        device = devices[device_key]
        for required in ("ADDRESS", "CREDENTIALS"):
            if required not in device:
                raise RuntimeError(f"HIK_CONFIG.DEVICES.{device_key} is missing '{required}'.")

        creds_key = device["CREDENTIALS"]
        hik_creds = hik_config.get("CREDENTIALS", {})
        if creds_key not in hik_creds:
            raise RuntimeError(f"Credentials '{creds_key}' not found in HIK_CONFIG.CREDENTIALS.")
        creds = hik_creds[creds_key]

        # Validate REDIS section exists and is reachable enough to build a client.
        get_redis_client()

        self.auth = HTTPDigestAuth(creds["USERNAME"], creds["PASSWORD"])
        proto = device.get("PROTOCOL", "http")
        port = device.get("PORT", "80")
        self.alert_url = "{}://{}:{}/ISAPI/Event/notification/alertStream".format(
            proto, device["ADDRESS"], port
        )
        return True

    def _work(self):
        # Drain anything left over from a previous Redis outage before reading new alerts.
        self._drain_to_redis()
        for alert in self._stream_alerts():
            self.process_alert(alert)