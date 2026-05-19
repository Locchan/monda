from collections import deque

from monda.utils.misc import read_config

_init_deque_size = read_config().get("HIK_CONFIG", {}).get("EVENT_DEQUE_MAX_SIZE", 30)
HIK_EVENTS_TOPIC = "hik_events"
HikEvents = deque(maxlen=_init_deque_size)


def is_ignored_event(name: str, state: str) -> bool:
    ignored = read_config().get("HIK_CONFIG", {}).get("IGNORED_EVENTS", {})
    if name not in ignored:
        return False
    states = ignored[name]
    if not states:
        return True
    return state in states


from monda.classes.workers.W_ConfigWatch import W_ConfigWatch
from monda.classes.workers.hik.W_HikProducer import W_HikProducer
from monda.classes.workers.hik.W_HikConsumer import W_HikConsumer

ENABLED_WORKERS = {
    "W_ConfigWatch": W_ConfigWatch,
    "W_HikProducer": W_HikProducer,
    "W_HikConsumer": W_HikConsumer,
}