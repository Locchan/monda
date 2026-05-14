import threading

import redis

from monda.utils.logger import get_logger
from monda.utils.misc import read_config

_client: redis.Redis | None = None
_lock = threading.Lock()

logger = get_logger()

def get_redis_client() -> redis.Redis:
    """Return the process-wide Redis client. Builds one on first use."""
    global _client
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        cfg = read_config().get("REDIS")
        if not cfg or "HOST" not in cfg:
            raise RuntimeError("REDIS section missing or has no HOST in config.")
        logger.info(f"Connected/Reconnected to redis at {cfg['HOST']}")
        _client = redis.Redis(
            host=cfg["HOST"],
            port=int(cfg.get("PORT", 6379)),
            db=int(cfg.get("DB", 0)),
            username=cfg.get("USERNAME"),
            password=cfg.get("PASSWORD"),
            socket_connect_timeout=5,
            socket_timeout=5,
            decode_responses=True,
        )
        return _client


def reset_redis_client() -> None:
    """Drop the cached client so the next get_redis_client() builds a fresh one."""
    global _client
    _client = None
