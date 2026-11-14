import json
import logging
from collections.abc import Generator

import redis as redis_lib
import requests
from requests.auth import HTTPDigestAuth

from monda.classes.base.Worker import Worker
from monda.classes.base.hik.HikEvent import HikEvent
from monda.classes.workers import HikEvents, HIK_EVENTS_TOPIC, is_ignored_event
from monda.utils.logger import get_logger
from monda.utils.misc import read_config
from monda.utils.redis_client import get_redis_client, reset_redis_client

logger: logging.Logger = get_logger()

# docs/hik.md
class W_HikProducer(Worker):

    alerts_buffer: list[str] = []

    worker_class_name = "W_HikProducer"
    worker_class_name_short = "W:HikProd"


    def _resolve_device(self) -> tuple[HTTPDigestAuth, str, str]:
        config = read_config()
        hik_config = config.get("HIK_CONFIG", {})
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
        username = creds["USERNAME"]
        password = creds["PASSWORD"]
        auth = HTTPDigestAuth(username, password)
        proto = device.get("PROTOCOL", "http")
        port = device.get("PORT", "80")
        alert_url = "{}://{}:{}/ISAPI/Event/notification/alertStream".format(
            proto, device["ADDRESS"], port
        )
        return auth, alert_url, username

    def process_alert(self, alert: str) -> None:
        event = HikEvent.from_xml(alert, source=self._instance_name)
        if is_ignored_event(event.name, event.state):
            return
        logger.debug(repr(event))
        max_size = read_config().get("HIK_CONFIG", {}).get("EVENT_DEQUE_MAX_SIZE", 30)
        if len(HikEvents) == max_size:
            logger.error(f"HikEvent queue is full ({max_size}). We're bleeding data!")
        elif len(HikEvents) > (max_size / 2):
            logger.warn(f"HikEvent queue is more than half-full ({max_size}).")
        HikEvents.append(event)
        if self._use_redis:
            self._drain_to_redis()

    def _drain_to_redis(self) -> None:
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

    def _stream_alerts(self, auth: HTTPDigestAuth, alert_url: str, username: str) -> Generator[str, None, None]:
        with requests.get(alert_url, auth=auth, stream=True, timeout=None) as response:
            if response.status_code != 200:
                logger.warning(f"Could not connect to alert stream ({alert_url}) as '{username}': {response.status_code}")
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


    def _initialize(self) -> bool:
        self._use_redis: bool = self.config.get("USE_REDIS", False)
        self._resolve_device()
        if self._use_redis:
            get_redis_client()
        self._update_status(f"Watching device '{self.config['DEVICE']}'.")
        return True

    def _work(self) -> None:
        if self._use_redis:
            self._drain_to_redis()
        auth, alert_url, username = self._resolve_device()
        device_name = self.config["DEVICE"]
        self._update_status(f"Connecting to '{device_name}'...")
        connected = False
        for alert in self._stream_alerts(auth, alert_url, username):
            if not connected:
                connected = True
                self._update_status(f"Connected to '{device_name}'.")
            self.process_alert(alert)
