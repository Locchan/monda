import json
import shlex
from datetime import datetime
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

import requests

from monda.classes.base.Worker import Worker
from monda.classes.jobs import ENABLED_JOBS
from monda.config_schema import JOB_SCHEMAS, UNSET, validate
from monda.utils.logger import get_logger
from monda.utils.misc import read_config, set_config_entry

logger = get_logger()

# docs/workers.md


class _JobSpec(NamedTuple):
    class_name: str
    instance_name: str
    params: dict
    silent: bool
    enabled: bool

    @property
    def key(self) -> str:
        return f"{self.class_name}/{self.instance_name}"


def _class_enabled(config: dict, class_name: str) -> bool:
    return bool(config.get("JOB_CONFIG", {}).get(class_name, {}).get("ENABLED", True))


def _merged_config(config: dict, spec: _JobSpec) -> dict:
    static = config.get("JOB_CONFIG", {}).get(spec.class_name, {}).get(spec.instance_name, {})
    if not isinstance(static, dict):
        static = {}
    return {**static, **spec.params}


def _configured_jobs(config: dict | None = None) -> dict[str, _JobSpec]:
    """Jobs defined on this daemon, keyed by ``JobClass/instance``.

    Cron entries supply runtime params. ``JOB_CONFIG`` instances fill in
    anything a cron entry did not already define. A class with ``ENABLED``
    false is included so a trigger can say it is disabled.
    """
    config = read_config() if config is None else config
    found: dict[str, _JobSpec] = {}

    cron = config.get("WORKER_CONFIG", {}).get("W_Cron", {})
    if isinstance(cron, dict):
        for worker_cfg in cron.values():
            if not isinstance(worker_cfg, dict):
                continue
            jobs = worker_cfg.get("JOBS", {})
            if not isinstance(jobs, dict):
                continue
            for job_name, spec in jobs.items():
                if not isinstance(job_name, str) or not isinstance(spec, dict):
                    continue
                class_name = spec.get("JOB_CLASS")
                if not isinstance(class_name, str) or class_name not in ENABLED_JOBS:
                    continue
                if "-" in class_name or "-" in job_name:
                    continue
                params = spec.get("PARAMS") or {}
                if not isinstance(params, dict):
                    params = {}
                found[f"{class_name}/{job_name}"] = _JobSpec(
                    class_name, job_name, dict(params), bool(spec.get("SILENT", False)),
                    _class_enabled(config, class_name),
                )

    job_config = config.get("JOB_CONFIG", {})
    if isinstance(job_config, dict):
        for class_name, class_cfg in job_config.items():
            if not isinstance(class_name, str) or class_name not in ENABLED_JOBS:
                continue
            if not isinstance(class_cfg, dict) or "-" in class_name:
                continue
            enabled = _class_enabled(config, class_name)
            for instance_name, instance_cfg in class_cfg.items():
                if not isinstance(instance_name, str) or not isinstance(instance_cfg, dict):
                    continue
                if "-" in instance_name:
                    continue
                key = f"{class_name}/{instance_name}"
                if key in found:
                    continue
                found[key] = _JobSpec(class_name, instance_name, {}, False, enabled)
    return found


def _resolve_job(jobs: dict[str, _JobSpec], name: str) -> _JobSpec | list[_JobSpec] | None:
    if name in jobs:
        return jobs[name]
    if "/" in name:
        return None
    matches = [spec for spec in jobs.values() if spec.instance_name == name]
    enabled = [spec for spec in matches if spec.enabled]
    if len(enabled) == 1:
        return enabled[0]
    if len(enabled) > 1:
        return enabled
    if len(matches) == 1:
        return matches[0]
    return None


def _tokenize(args: str) -> list[str]:
    lexer = shlex.shlex(args, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _coerce_arg(key: str, ftype: str, raw: str) -> tuple[Any, str | None]:
    if ftype == "int":
        try:
            return int(raw), None
        except ValueError:
            return None, f"{key} must be an integer."
    if ftype == "bool":
        if raw.lower() in ("y", "yes", "true", "1"):
            return True, None
        if raw.lower() in ("n", "no", "false", "0"):
            return False, None
        return None, f"{key} must be yes or no."
    if ftype == "list_str":
        return [part.strip() for part in raw.split(",") if part.strip()], None
    if ftype == "list_int":
        try:
            return [int(part.strip()) for part in raw.split(",") if part.strip()], None
        except ValueError:
            return None, f"{key} must be comma-separated integers."
    if ftype in ("json", "named_list"):
        try:
            return json.loads(raw), None
        except json.JSONDecodeError as e:
            return None, f"{key} must be JSON: {e.msg}."
    return raw, None


def _parse_overrides(class_name: str, tokens: list[str]) -> tuple[dict, str | None]:
    fields = {field.key: field for field in JOB_SCHEMAS[class_name].fields if field.key != "ENABLED"}
    overrides: dict = {}
    for token in tokens:
        if "=" not in token:
            return {}, f"Expected KEY=VALUE, got '{token}'."
        key, raw = token.split("=", 1)
        if not key:
            return {}, "Expected KEY=VALUE."
        if key == "ENABLED":
            return {}, "ENABLED cannot be set with /trigger."
        field = fields.get(key)
        if field is None:
            return {}, f"Unknown argument '{key}' for {class_name}."
        if key in overrides:
            return {}, f"Duplicate argument '{key}'."
        value, err = _coerce_arg(key, field.type, raw)
        if err:
            return {}, err
        overrides[key] = value
    return overrides, None


def _format_default(value: Any) -> str:
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _format_schema(class_name: str) -> str:
    schema = JOB_SCHEMAS[class_name]
    required: list[str] = []
    optional: list[str] = []
    for field in schema.fields:
        if field.key == "ENABLED":
            continue
        line = f"  {field.key} ({field.type}) — {field.desc}"
        if field.default is not UNSET:
            line += f" [default {_format_default(field.default)}]"
        if field.optional or field.default is not UNSET:
            optional.append(line)
        else:
            required.append(line)
    parts = [class_name, schema.description]
    if required:
        parts.extend(["", "Required:", *required])
    if optional:
        parts.extend(["", "Optional:", *optional])
    return "\n".join(parts)


def _message_alert_time(message_date: int | float | None) -> str | None:
    if not isinstance(message_date, (int, float)):
        return None
    name = read_config().get("TZ", "UTC")
    try:
        tz = ZoneInfo(name)
    except Exception:
        logger.error(f"TZ {name!r} is not a valid timezone.")
        return None
    return datetime.fromtimestamp(int(message_date), tz).isoformat()


def _start_job(spec: _JobSpec, overrides: dict, message_date: int | float | None = None) -> str:
    if not spec.enabled:
        return f"{spec.key} is disabled."
    params = {**spec.params, **overrides}
    if spec.class_name == "J_HikAlertClip":
        alert_time = _message_alert_time(message_date)
        if alert_time is None:
            return f"Could not start {spec.key}: the message has no timestamp."
        params["ALERT_TIME"] = alert_time
    spec = spec._replace(params=params)
    config = read_config()
    errors = validate(_merged_config(config, spec), JOB_SCHEMAS[spec.class_name].fields)
    if errors:
        message = f"Could not start {spec.key}: {'; '.join(errors)}"
        if any(error.endswith("is required") for error in errors):
            message += "\n\n" + _format_schema(spec.class_name)
        return message
    job = ENABLED_JOBS[spec.class_name](spec.instance_name, spec.params, silent=spec.silent)
    if not job.initialize() or job.run() is None:
        return f"Could not start {spec.key}. Check monda logs."
    if overrides:
        logger.info(f"Telegram triggered job {spec.key} with {', '.join(overrides)}.")
    else:
        logger.info(f"Telegram triggered job {spec.key}.")
    return f"Triggered {spec.key}."


def _cmd_trigger(args: str, message_date: int | float | None = None) -> str:
    try:
        tokens = _tokenize(args)
    except ValueError as e:
        return f"Could not parse arguments: {e}"
    if not tokens:
        jobs = _configured_jobs()
        enabled = sorted(spec.key for spec in jobs.values() if spec.enabled)
        if not enabled:
            return "No enabled jobs."
        return "Enabled jobs:\n" + "\n".join(enabled)

    jobs = _configured_jobs()
    resolved = _resolve_job(jobs, tokens[0])
    if resolved is None:
        return f"Unknown job '{tokens[0]}'. Send /trigger to list enabled jobs."
    if isinstance(resolved, list):
        keys = "\n".join(sorted(spec.key for spec in resolved))
        return f"Several jobs match '{tokens[0]}':\n{keys}"
    if not resolved.enabled:
        return f"{resolved.key} is disabled."
    overrides, err = _parse_overrides(resolved.class_name, tokens[1:])
    if err:
        return err
    return _start_job(resolved, overrides, message_date)


def _cmd_hik_sender(_args: str) -> str:
    current = (read_config()
               .get("JOB_CONFIG", {})
               .get("J_HikAlertSnap", {})
               .get("ENABLED", True))

    desired = not current
    set_config_entry("JOB_CONFIG/J_HikAlertSnap/ENABLED", desired)
    action = "Enabled" if desired else "Disabled"
    return f"{action} Hik sender job."


COMMANDS = {
    "/hik_sender": (_cmd_hik_sender, "Toggle Hik snapshot alerts on/off"),
    "/trigger": (_cmd_trigger, "List enabled jobs, or run one with KEY=VALUE overrides"),
    "/help": (None, "Show available commands"),
}


def _cmd_help(_args: str) -> str:
    lines = [f"{cmd} — {desc}" for cmd, (_, desc) in COMMANDS.items()]
    return "\n".join(lines)


COMMANDS["/help"] = (_cmd_help, COMMANDS["/help"][1])


def parse_command(chat_id: int, message_text: str, message_date: int | float | None = None) -> str | None:
    parts = message_text.split(maxsplit=1)
    cmd = parts[0].split("@")[0]
    args = parts[1] if len(parts) > 1 else ""

    entry = COMMANDS.get(cmd)
    if entry is None:
        return f"Unknown command: {cmd}"
    handler, _ = entry
    if handler is _cmd_trigger:
        return handler(args, message_date)
    return handler(args)


class W_TelegramBot(Worker):

    worker_class_name = "W_TelegramBot"
    worker_class_name_short = "W:Telegram"


    def __init__(self, name: str, interval_s: int):
        super().__init__(name, interval_s)
        self._last_update_id = 0

    def _initialize(self):
        tg_config = read_config().get("TELEGRAM", {})
        token = tg_config.get("BOT_TOKEN")
        if not token:
            logger.error("TELEGRAM.BOT_TOKEN is missing from config.")
            return False
        chat_ids = tg_config.get("CHAT_IDS")
        if not chat_ids:
            logger.error("TELEGRAM.CHAT_IDS is missing from config.")
            return False
        self._api_base = f"https://api.telegram.org/bot{token}"
        try:
            resp = requests.get(f"{self._api_base}/getMe", timeout=10)
            resp.raise_for_status()
            bot_info = resp.json().get("result", {})
            username = bot_info.get('username', '?')
            logger.info(f"Telegram bot connected: @{username}")
            self._update_status(f"Bot @{username} connected.")
        except Exception as e:
            logger.error(f"Could not connect to Telegram API: {e}")
            return False
        return True

    def _get_allowed_chat_ids(self) -> set[int]:
        raw = read_config().get("TELEGRAM", {}).get("CHAT_IDS", [])
        return {int(cid) for cid in raw}

    def _get_updates(self) -> list[dict]:
        config = read_config()
        token = config.get("TELEGRAM", {}).get("BOT_TOKEN", "")
        api_base = f"https://api.telegram.org/bot{token}"
        try:
            resp = requests.get(f"{api_base}/getUpdates", params={
                "offset": self._last_update_id + 1,
                "timeout": 0,
            }, timeout=10)
            resp.raise_for_status()
            return resp.json().get("result", [])
        except Exception as e:
            logger.warning(f"Telegram getUpdates failed: {e}")
            return []

    def _send_message(self, chat_id: int, text: str) -> None:
        config = read_config()
        token = config.get("TELEGRAM", {}).get("BOT_TOKEN", "")
        api_base = f"https://api.telegram.org/bot{token}"
        try:
            resp = requests.post(f"{api_base}/sendMessage", json={
                "chat_id": chat_id,
                "text": text,
            }, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Telegram sendMessage failed: {e}")

    def _work(self):
        allowed = self._get_allowed_chat_ids()
        updates = self._get_updates()
        for update in updates:
            update_id = update.get("update_id", 0)
            if update_id > self._last_update_id:
                self._last_update_id = update_id

            message = update.get("message", {})
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")

            if chat_id is None or not text:
                continue

            if chat_id not in allowed:
                logger.debug(f"Telegram message from unauthorized chat {chat_id}, ignoring.")
                continue

            if not text.startswith("/"):
                continue

            result = parse_command(chat_id, text, message.get("date"))
            if isinstance(result, str):
                self._send_message(chat_id, result)
