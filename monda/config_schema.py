from dataclasses import dataclass, field as dc_field
from typing import Any, Callable

UNSET = object()

_EXPECTED_TYPE: dict[str, type | None] = {
    "str":       str,
    "int":       int,
    "bool":      bool,
    "list_str":  list,
    "list_int":  list,
    "json":      None,   # any
    "named_list": dict,
}


def validate(config: dict, fields: list["Field"]) -> list[str]:
    errors: list[str] = []
    for field in fields:
        val = config.get(field.key, UNSET)
        if val is UNSET:
            if not field.optional and field.default is UNSET:
                errors.append(f"'{field.key}' is required")
            continue
        expected = _EXPECTED_TYPE.get(field.type)
        if expected is not None and not isinstance(val, expected):
            errors.append(
                f"'{field.key}' must be {field.type}, got {type(val).__name__}"
            )
    return errors


@dataclass
class Field:
    key: str
    desc: str
    type: str  # "str" | "int" | "bool" | "list_str" | "list_int" | "json" | "named_list"
    default: Any = UNSET
    optional: bool = False
    sub_fields: list["Field"] = dc_field(default_factory=list)
    choices: Callable[[], list[str]] | None = None


_ENABLED_FIELD = Field("ENABLED", "Enable this instance", "bool", True, optional=True)

# ── Global ────────────────────────────────────────────────────────────────────

GLOBAL_FIELDS: list[Field] = [
    Field("NAME",                  "Daemon name",                       "str", "monda"),
    Field("DEBUG",                 "Debug logging",                     "bool", False),
    Field("TZ",                    "Timezone",                          "str", "UTC"),
    Field("CONFIG_WATCH_INTERVAL", "Config reload interval (seconds)",  "int", 5),
    Field("PID_FILE",              "PID file path",                     "str", optional=True),
    Field("LOG_DIR",               "Log directory (per-worker/job debug files)", "str", optional=True),
    Field("LOG_FILE",              "Deprecated — use LOG_DIR instead",  "str", optional=True),
]

# ── LED targets ───────────────────────────────────────────────────────────────

LED_TARGET_FIELDS: list[Field] = [
    Field("BASEDIR", "Directory for outgoing LED messages", "str"),
]

# ── Telegram ──────────────────────────────────────────────────────────────────

TELEGRAM_FIELDS: list[Field] = [
    Field("BOT_TOKEN", "Telegram bot token",             "str"),
    Field("CHAT_IDS",  "Allowed chat IDs (comma-sep)",   "list_int"),
]

# ── Hikvision ─────────────────────────────────────────────────────────────────

HIK_GLOBAL_FIELDS: list[Field] = [
    Field("EVENT_DEQUE_MAX_SIZE", "In-memory event queue size", "int", 30),
]

HIK_DEVICE_FIELDS: list[Field] = [
    Field("ADDRESS",     "Device IP or hostname",            "str"),
    Field("CREDENTIALS", "Credentials key (from CREDENTIALS section)", "str"),
    Field("PROTOCOL",    "Protocol (http/https)",            "str", "http", optional=True),
    Field("PORT",        "HTTP port",                        "str", "80",   optional=True),
]

HIK_CRED_FIELDS: list[Field] = [
    Field("USERNAME", "Username", "str"),
    Field("PASSWORD", "Password", "str"),
]

# ── Backup sub-entry schemas ───────────────────────────────────────────────────

_BACKUP_RAW_ENTRY: list[Field] = [
    Field("PATH",                    "Directory to watch",              "str"),
    Field("EXPECTED_PERIOD_MINUTES", "Expected backup period (min)",    "int"),
    Field("PERMITTED_LAG_MINUTES",   "Allowed lag beyond period (min)", "int"),
]

_BACKUP_BORG_ENTRY: list[Field] = [
    Field("PATH",                    "Borg repository path",            "str"),
    Field("EXPECTED_PERIOD_MINUTES", "Expected backup period (min)",    "int"),
    Field("PERMITTED_LAG_MINUTES",   "Allowed lag beyond period (min)", "int"),
    Field("PASSPHRASE",              "Borg passphrase",                 "str", optional=True),
]

# ── W_Cron job sub-entry schema ───────────────────────────────────────────────

_CRON_JOB_ENTRY: list[Field] = [
    Field("SCHEDULE",  "Cron expression (e.g. 0 * * * *)", "str"),
    Field("JOB_CLASS", "Job class name",  "str", choices=lambda: list(JOB_SCHEMAS.keys())),
    Field("SILENT",    "Suppress info logs",                "bool", False, optional=True),
    Field("PARAMS",    "Extra params passed to job (JSON)", "json",        optional=True),
]

# ── Worker schemas ────────────────────────────────────────────────────────────

@dataclass
class WorkerSchema:
    description: str
    fields: list[Field]


WORKER_SCHEMAS: dict[str, WorkerSchema] = {
    "W_MondaStatus": WorkerSchema(
        "HTTP status endpoint — serves GET /status as JSON",
        [
            Field("PORT",      "HTTP port",                        "int"),
            Field("INTERVAL",  "Health check interval (seconds)",  "int", 30),
            Field("EDIT_MOTD", "Write status to MOTD file",        "bool", False, optional=True),
            Field("MOTD_FILE", "MOTD file path",                   "str", "/etc/motd", optional=True),
            _ENABLED_FIELD,
        ],
    ),
    "W_ConfigWatch": WorkerSchema(
        "Hot-reload config.json when it changes on disk",
        [
            Field("INTERVAL", "File check interval (seconds)", "int", 5),
            _ENABLED_FIELD,
        ],
    ),
    "W_SSHLoginWatcher": WorkerSchema(
        "Alert on SSH logins via audit log, auth.log, or journalctl",
        [
            Field("INTERVAL",     "Poll interval (seconds)",                 "int", 10),
            Field("ALERT_TARGET", "LED alert target name",                   "str", "general", optional=True),
            Field("LOG_PATH",     "SSH log file (auto-detected if omitted)", "str", optional=True),
            _ENABLED_FIELD,
        ],
    ),
    "W_SystemdWatcher": WorkerSchema(
        "Alert when any systemd service enters the failed state",
        [
            Field("INTERVAL",     "Poll interval (seconds)",        "int", 60),
            Field("ALERT_TARGET", "LED alert target name",          "str", "general", optional=True),
            Field("IGNORE",       "Services to ignore (comma-sep)", "list_str", optional=True),
            _ENABLED_FIELD,
        ],
    ),
    "W_DockerWatcher": WorkerSchema(
        "Alert on exited, dead, restarting, or crash-looping Docker containers",
        [
            Field("INTERVAL",     "Poll interval (seconds)",                  "int", 60),
            Field("ALERT_TARGET", "LED alert target name",                    "str", "general", optional=True),
            Field("IGNORE",       "Container names to ignore (comma-sep)",    "list_str", optional=True),
            _ENABLED_FIELD,
        ],
    ),
    "W_BackupWatcherRaw": WorkerSchema(
        "Alert when filesystem backups are overdue (checks newest file mtime)",
        [
            Field("INTERVAL",     "Poll interval (seconds)", "int", 3600),
            Field("ALERT_TARGET", "LED alert target name",   "str", "general", optional=True),
            Field("BACKUPS",      "Backup targets",          "named_list", sub_fields=_BACKUP_RAW_ENTRY),
            _ENABLED_FIELD,
        ],
    ),
    "W_BackupWatcherBorg": WorkerSchema(
        "Alert when Borg backup archives are overdue",
        [
            Field("INTERVAL",     "Poll interval (seconds)", "int", 3600),
            Field("ALERT_TARGET", "LED alert target name",   "str", "general", optional=True),
            Field("BACKUPS",      "Borg repositories",       "named_list", sub_fields=_BACKUP_BORG_ENTRY),
            _ENABLED_FIELD,
        ],
    ),
    "W_Cron": WorkerSchema(
        "Schedule periodic jobs on cron expressions",
        [
            Field("INTERVAL", "Tick interval (seconds)", "int", 60),
            Field("JOBS",     "Scheduled jobs",          "named_list", sub_fields=_CRON_JOB_ENTRY),
            _ENABLED_FIELD,
        ],
    ),
    "W_TelegramBot": WorkerSchema(
        "Telegram bot — polls for commands and dispatches them",
        [
            Field("INTERVAL", "Polling interval (seconds)", "int", 5),
            _ENABLED_FIELD,
        ],
    ),
    "W_HikProducer": WorkerSchema(
        "Stream events from a Hikvision camera over ISAPI",
        [
            Field("INTERVAL",  "Reconnect check interval (seconds)",  "int", 30),
            Field("DEVICE",    "Device key from HIK_CONFIG.DEVICES",  "str"),
            Field("USE_REDIS", "Push events to Redis instead of RAM", "bool", False, optional=True),
            _ENABLED_FIELD,
        ],
    ),
    "W_HikConsumer": WorkerSchema(
        "Process Hikvision motion events and trigger snapshot jobs",
        [
            Field("INTERVAL",  "Poll interval (seconds)",                    "int", 1),
            Field("USE_REDIS", "Consume events from Redis instead of RAM",   "bool", False, optional=True),
            _ENABLED_FIELD,
        ],
    ),
}

# ── Job schemas ───────────────────────────────────────────────────────────────

@dataclass
class JobSchema:
    description: str
    fields: list[Field]


JOB_SCHEMAS: dict[str, JobSchema] = {
    "J_HikAlertSnap": JobSchema(
        "Capture a Hikvision snapshot and send it as an LED alert",
        [
            Field("HIK_DEVICE", "Device key from HIK_CONFIG.DEVICES", "str"),
            Field("MESSAGE",    "Alert message text",                  "str"),
            Field("CHANNEL",    "ISAPI channel number",                "str", "101", optional=True),
            _ENABLED_FIELD,
        ],
    ),
    "J_HikSnap": JobSchema(
        "Capture a Hikvision snapshot and save to disk",
        [
            Field("HIK_DEVICE", "Device key from HIK_CONFIG.DEVICES", "str"),
            Field("DEST_DIR",   "Directory to save snapshots",        "str"),
            Field("CHANNEL",    "ISAPI channel number",               "str", "101", optional=True),
            _ENABLED_FIELD,
        ],
    ),
    "J_HikSnapArch": JobSchema(
        "Archive Hikvision snapshots from source to destination",
        [
            Field("SRC_DIR",  "Source snapshot directory",     "str"),
            Field("DEST_DIR", "Destination archive directory", "str"),
            _ENABLED_FIELD,
        ],
    ),
}
