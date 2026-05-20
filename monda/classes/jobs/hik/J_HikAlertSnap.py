import os
import tempfile
import time

import requests
from requests.auth import HTTPDigestAuth

from monda.classes.base.Job import Job
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger
from monda.utils.misc import read_config

logger = get_logger()


class J_HikAlertSnap(Job):

    job_class_name = "J_HikAlertSnap"
    job_class_name_short = "J:HikSnap"
    required_config_entries = ["HIK_DEVICE", "MESSAGE"]

    _last_snap: dict[str, float] = {}

    @classmethod
    def acquire(cls, device_key: str) -> bool:
        period = (read_config()
                  .get("JOB_CONFIG", {})
                  .get("J_HikAlertSnap", {})
                  .get("ALERT_PERIOD", 15))
        last = cls._last_snap.get(device_key)
        now = time.monotonic()
        if last is not None and (now - last) < period:
            return False
        cls._last_snap[device_key] = now
        return True

    def _initialize(self):
        config = read_config()
        hik_config = config.get("HIK_CONFIG", {})

        device_key = self.config["HIK_DEVICE"]
        devices = hik_config.get("DEVICES", {})
        if device_key not in devices:
            logger.error(f"Device '{device_key}' not found in HIK_CONFIG.DEVICES.")
            return False
        device = devices[device_key]

        for required in ("ADDRESS", "CREDENTIALS"):
            if required not in device:
                logger.error(f"HIK_CONFIG.DEVICES.{device_key} is missing '{required}'.")
                return False

        creds_key = device["CREDENTIALS"]
        hik_creds = hik_config.get("CREDENTIALS", {})
        if creds_key not in hik_creds:
            logger.error(f"Credentials '{creds_key}' not found in HIK_CONFIG.CREDENTIALS.")
            return False

        return True

    def _work(self):
        config = read_config()
        hik_config = config.get("HIK_CONFIG", {})
        device_key = self.config["HIK_DEVICE"]
        device = hik_config["DEVICES"][device_key]
        creds = hik_config["CREDENTIALS"][device["CREDENTIALS"]]

        auth = HTTPDigestAuth(creds["USERNAME"], creds["PASSWORD"])
        proto = device.get("PROTOCOL", "http")
        port = device.get("PORT", "80")
        channel = self.config.get("CHANNEL", "101")
        snap_url = f"{proto}://{device['ADDRESS']}:{port}/ISAPI/Streaming/channels/{channel}/picture"
        message = self.config["MESSAGE"]

        logger.info(f"Requesting snapshot from {snap_url}")
        response = requests.get(snap_url, auth=auth, timeout=10)
        if response.status_code != 200:
            raise RuntimeError(f"Snapshot request failed: HTTP {response.status_code}")

        fd, tmp_path = tempfile.mkstemp(suffix=".jpg", prefix="hiksnap_")
        try:
            os.write(fd, response.content)
            os.close(fd)
        except BaseException:
            os.close(fd)
            os.unlink(tmp_path)
            raise

        send_alert(message, files=[tmp_path])
