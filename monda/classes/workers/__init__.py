from collections import deque

from monda.utils.misc import read_config

_hik_config = read_config().get("HIK_CONFIG", {})
HIK_EVENT_DEQUE_MAX_SIZE = _hik_config.get("EVENT_DEQUE_MAX_SIZE", 30)
HIK_EVENTS_TOPIC = "hik_events"
HikEvents = deque(maxlen=HIK_EVENT_DEQUE_MAX_SIZE)

_ignored_events: dict[str, list[str]] = _hik_config.get("IGNORED_EVENTS", {})


def is_ignored_event(name: str, state: str) -> bool:
    """True if this event should be filtered out.

    Lookup table is HIK_CONFIG.IGNORED_EVENTS: {event_name: [state, ...]}.
    An empty state list means *every* state of that event is ignored.
    """
    if name not in _ignored_events:
        return False
    states = _ignored_events[name]
    if not states:
        return True
    return state in states


from monda.classes.workers.W_HikProducer import W_HikProducer
from monda.classes.workers.W_HikConsumer import W_HikConsumer

ENABLED_WORKERS = {
    "W_HikProducer": W_HikProducer,
    "W_HikConsumer": W_HikConsumer,
}