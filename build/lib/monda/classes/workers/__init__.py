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


from monda.classes.workers.W_BackupWatcherBorg import W_BackupWatcherBorg
from monda.classes.workers.W_BackupWatcherRaw import W_BackupWatcherRaw
from monda.classes.workers.W_ConfigWatch import W_ConfigWatch
from monda.classes.workers.W_Cron import W_Cron
from monda.classes.workers.W_DockerWatcher import W_DockerWatcher
from monda.classes.workers.W_MDadm import W_MDadm
from monda.classes.workers.W_MondaStatus import W_MondaStatus
from monda.classes.workers.W_SSHLoginWatcher import W_SSHLoginWatcher
from monda.classes.workers.W_SystemdWatcher import W_SystemdWatcher
from monda.classes.workers.hik.W_HikProducer import W_HikProducer
from monda.classes.workers.hik.W_HikConsumer import W_HikConsumer
from monda.classes.workers.telegram.W_TelegramBot import W_TelegramBot

ENABLED_WORKERS = {
    "W_BackupWatcherBorg": W_BackupWatcherBorg,
    "W_BackupWatcherRaw": W_BackupWatcherRaw,
    "W_ConfigWatch": W_ConfigWatch,
    "W_Cron": W_Cron,
    "W_DockerWatcher": W_DockerWatcher,
    "W_MDadm": W_MDadm,
    "W_MondaStatus": W_MondaStatus,
    "W_SSHLoginWatcher": W_SSHLoginWatcher,
    "W_SystemdWatcher": W_SystemdWatcher,
    "W_HikProducer": W_HikProducer,
    "W_HikConsumer": W_HikConsumer,
    "W_TelegramBot": W_TelegramBot,
}

from monda.config_schema import WORKER_SCHEMAS  # noqa: E402
_missing = [k for k in ENABLED_WORKERS if k not in WORKER_SCHEMAS]
if _missing:
    import sys
    print(f"FATAL: workers without schema: {', '.join(_missing)}", file=sys.stderr)
    sys.exit(1)