import logging
import os
from datetime import datetime

import requests
from requests.auth import HTTPDigestAuth

from monda.classes.base.Job import Job
from monda.utils.logger import get_logger
from monda.utils.misc import read_config

logger: logging.Logger = get_logger()


# docs/jobs.md
class J_HikSnap(Job):

    job_class_name = "J_HikSnap"
    job_class_name_short = "J:HkSnap"

    def _initialize(self) -> bool:
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
        if creds_key not in hik_config.get("CREDENTIALS", {}):
            logger.error(f"Credentials '{creds_key}' not found in HIK_CONFIG.CREDENTIALS.")
            return False

        return True

    def _work(self) -> None:
        config = read_config()
        hik_config = config.get("HIK_CONFIG", {})
        device_key = self.config["HIK_DEVICE"]
        dest_dir = self.config["DEST_DIR"]
        device = hik_config["DEVICES"][device_key]
        creds = hik_config["CREDENTIALS"][device["CREDENTIALS"]]

        proto = device.get("PROTOCOL", "http")
        port = device.get("PORT", "80")
        channel = self.config.get("CHANNEL", "101")
        snap_url = f"{proto}://{device['ADDRESS']}:{port}/ISAPI/Streaming/channels/{channel}/picture"

        self._info(f"Requesting snapshot from {snap_url}")
        auth = HTTPDigestAuth(creds["USERNAME"], creds["PASSWORD"])
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(6):
            try:
                response = requests.get(snap_url, auth=auth, timeout=2)
                if response.status_code == 200:
                    break
                last_exc = RuntimeError(f"Snapshot request failed: HTTP {response.status_code}")
            except requests.RequestException as e:
                last_exc = e
            logger.warning(f"Snapshot attempt {attempt + 1}/6 failed: {last_exc}")
        else:
            raise last_exc

        os.makedirs(dest_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest_path = os.path.join(dest_dir, f"{device_key}_{timestamp}.jpg")
        with open(dest_path, "wb") as f:
            f.write(response.content)
        self._info(f"Snapshot saved to {dest_path}")
