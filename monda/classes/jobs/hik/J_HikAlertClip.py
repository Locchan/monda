import logging
import os
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from monda.classes.base.Job import Job
from monda.utils.led_alert import send_alert
from monda.utils.logger import get_logger
from monda.utils.misc import read_config

logger: logging.Logger = get_logger()

_DOWNLOAD_ATTEMPTS = 4
_RETRY_DELAY_S = 5
_MIN_BYTES = 1024
# Extend the RTSP range by one GOP on each side. This NVR places keyframes
# about 4s apart, and playback starts on the keyframe at or before starttime.
_KEYFRAME_MARGIN = 8.0
# Playback of the latest seconds is not available the moment they happen.
_PLAYBACK_LAG = 10.0
# The NVR goes silent after endtime instead of closing; this is how long
# ffmpeg waits before finishing the file.
_RTSP_TIMEOUT_US = 8_000_000
_RECORD_SLACK_S = 45


class _DownloadError(RuntimeError):
    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _config_tz() -> ZoneInfo:
    name = read_config().get("TZ", "UTC")
    try:
        return ZoneInfo(name)
    except Exception as e:
        raise _DownloadError(f"TZ {name!r} is not a valid timezone.", retryable=False) from e


def _rtsp_stamp(moment: datetime) -> str:
    # The NVR indexes recordings on its local clock and still writes Z.
    return moment.astimezone(_config_tz()).strftime("%Y%m%dT%H%M%SZ")


def _playback_url(
    user: str, password: str, host: str, port: str, channel: str, start: datetime, end: datetime,
) -> str:
    return (
        f"rtsp://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/Streaming/tracks/{quote(str(channel), safe='')}/"
        f"?starttime={_rtsp_stamp(start)}&endtime={_rtsp_stamp(end)}"
    )


def _redact(text: str, *secrets: str) -> str:
    for secret in secrets:
        if not secret:
            continue
        text = text.replace(secret, "***")
        text = text.replace(quote(secret, safe=""), "***")
    return text


# docs/jobs.md
class J_HikAlertClip(Job):

    job_class_name = "J_HikAlertClip"
    job_class_name_short = "J:HikClip"

    _last_clip: dict[str, float] = {}

    @classmethod
    def acquire(cls, device_key: str) -> bool:
        period = (read_config()
                  .get("JOB_CONFIG", {})
                  .get("J_HikAlertClip", {})
                  .get("ALERT_PERIOD", 60))
        last = cls._last_clip.get(device_key)
        now = time.monotonic()
        if last is not None and (now - last) < period:
            return False
        cls._last_clip[device_key] = now
        return True

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

        before = int(self.config.get("BEFORE_SEC", 10))
        after = int(self.config.get("AFTER_SEC", 10))
        if before < 0 or after < 0:
            logger.error("BEFORE_SEC and AFTER_SEC must be >= 0.")
            return False
        if before + after == 0:
            logger.error("BEFORE_SEC and AFTER_SEC cannot both be 0.")
            return False

        raw_time = self.config.get("ALERT_TIME")
        if not raw_time:
            logger.error("ALERT_TIME was not provided.")
            return False
        try:
            alert_time = datetime.fromisoformat(raw_time)
        except ValueError:
            logger.error(f"ALERT_TIME is not ISO-8601: {raw_time!r}")
            return False
        try:
            tz = ZoneInfo(config.get("TZ", "UTC"))
        except Exception as e:
            logger.error(f"Could not apply TZ to ALERT_TIME: {e}")
            return False
        alert_time = alert_time.replace(tzinfo=tz) if alert_time.tzinfo is None else alert_time.astimezone(tz)

        self._alert_time = alert_time
        self._before_sec = before
        self._after_sec = after
        return True

    def _work(self) -> None:
        start = self._alert_time - timedelta(seconds=self._before_sec)
        end = self._alert_time + timedelta(seconds=self._after_sec)
        # The URL runs one GOP past `end`. Wait until that playback end, plus
        # the lag, or the NVR answers 400 for footage it has not indexed yet.
        ready = end + timedelta(seconds=_KEYFRAME_MARGIN + _PLAYBACK_LAG)
        self._wait_until(ready)

        config = read_config()
        hik_config = config["HIK_CONFIG"]
        device_key = self.config["HIK_DEVICE"]
        device = hik_config["DEVICES"][device_key]
        creds = hik_config["CREDENTIALS"][device["CREDENTIALS"]]

        port = str(device.get("RTSP_PORT", "554"))
        channel = self.config.get("CHANNEL", "101")
        self._info(
            f"Recording clip from {start.isoformat()} to {end.isoformat()} "
            f"({self._before_sec}s before, {self._after_sec}s after the alert)."
        )
        tmp_path = self._download_clip(
            device["ADDRESS"], port, creds["USERNAME"], creds["PASSWORD"],
            channel, start, end, device_key,
        )
        send_alert(self.config["MESSAGE"], target="dacha_alerts", files=[tmp_path])

    def _wait_until(self, end: datetime) -> None:
        delay = end.timestamp() - time.time()
        if delay <= 0:
            self._info("Post-alert window has already elapsed, downloading.")
            return
        shown = f"{delay:.0f}s" if delay >= 10 else f"{delay:.1f}s"
        self._info(f"Waiting {shown} until {_PLAYBACK_LAG:.0f}s after the playback end.")
        time.sleep(delay)

    def _download_clip(
        self, host: str, port: str, user: str, password: str, channel: str,
        start: datetime, end: datetime, device_key: str,
    ) -> str:
        # Ask for a GOP before the start and a GOP after the end. Playback
        # begins on a keyframe, so this keeps every second of [start, end].
        play_start = start - timedelta(seconds=_KEYFRAME_MARGIN)
        play_end = end + timedelta(seconds=_KEYFRAME_MARGIN)
        requested = (end - start).total_seconds()
        # The clip begins at or before play_start, so it reaches `end` only
        # once it is at least this long. The NVR sometimes stops early.
        needed = requested + _KEYFRAME_MARGIN
        cap = requested + 3 * _KEYFRAME_MARGIN
        url = _playback_url(user, password, host, port, channel, play_start, play_end)

        stamp = self._alert_time.strftime("%Y%m%d_%H%M%S")
        safe_key = device_key.replace(os.sep, "_")
        prefix = f"hikclip_{safe_key}_{stamp}_"
        for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
            fd, dest = tempfile.mkstemp(suffix=".mp4", prefix=prefix)
            os.close(fd)
            try:
                _record_rtsp(url, dest, cap, user, password)
                duration = _media_duration(dest)
                if duration < needed:
                    raise _DownloadError(
                        f"NVR sent {duration:.1f}s, need {needed:.1f}s to cover the requested window."
                    )
                logger.info(f"Clip is {duration:.1f}s and contains the requested {requested:.1f}s.")
                return dest
            except _DownloadError as e:
                _unlink(dest)
                if not e.retryable or attempt == _DOWNLOAD_ATTEMPTS:
                    raise
                logger.warning(f"Clip download attempt {attempt}/{_DOWNLOAD_ATTEMPTS} failed: {e}")
                time.sleep(_RETRY_DELAY_S)
        raise RuntimeError("unreachable")


def _record_rtsp(url: str, dest: str, cap: float, user: str, password: str) -> None:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-rtsp_transport", "tcp",
        "-timeout", str(_RTSP_TIMEOUT_US),
        "-i", url,
        "-t", f"{cap:.3f}",
        "-c", "copy",
        "-movflags", "+faststart",
        "-y", dest,
    ]
    err_fd, err_path = tempfile.mkstemp(prefix="hikclip_ffmpeg_", suffix=".log")
    os.close(err_fd)
    try:
        with open(err_path, "wb") as err_file:
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err_file)
            except FileNotFoundError as e:
                raise _DownloadError("ffmpeg is required to record the clip.", retryable=False) from e
            try:
                code = proc.wait(timeout=cap + _RECORD_SLACK_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise _DownloadError("RTSP recording timed out.")
        with open(err_path, "r", encoding="utf-8", errors="replace") as f:
            err = _redact(f.read()[-800:].strip(), user, password)
    finally:
        _unlink(err_path)
    if code != 0:
        raise _DownloadError(f"ffmpeg failed ({code}): {err or 'no output'}")
    if not os.path.isfile(dest) or os.path.getsize(dest) < _MIN_BYTES:
        raise _DownloadError("Recorded clip is too small.")


def _media_duration(path: str) -> float:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    except FileNotFoundError as e:
        raise _DownloadError("ffprobe is required to check the clip.", retryable=False) from e
    if proc.returncode != 0:
        detail = proc.stderr[-400:].strip()
        raise _DownloadError(f"ffprobe failed: {detail or 'no output'}")
    try:
        return float(proc.stdout.strip())
    except ValueError as e:
        raise _DownloadError(f"ffprobe returned no duration: {proc.stdout.strip()!r}") from e
