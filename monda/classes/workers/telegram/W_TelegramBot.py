import requests

from monda.classes.base.Worker import Worker
from monda.utils.logger import get_logger
from monda.utils.misc import read_config, set_config_entry

logger = get_logger()


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
    "/help": (None, "Show available commands"),
}


def _cmd_help(_args: str) -> str:
    lines = [f"{cmd} — {desc}" for cmd, (_, desc) in COMMANDS.items()]
    return "\n".join(lines)


COMMANDS["/help"] = (_cmd_help, COMMANDS["/help"][1])


def parse_command(chat_id: int, message_text: str) -> str | None:
    parts = message_text.split(maxsplit=1)
    cmd = parts[0].split("@")[0]
    args = parts[1] if len(parts) > 1 else ""

    entry = COMMANDS.get(cmd)
    if entry is None:
        return f"Unknown command: {cmd}"
    handler, _ = entry
    return handler(args)


class W_TelegramBot(Worker):

    worker_class_name = "W_TelegramBot"
    worker_class_name_short = "W:Telegram"

    required_config_entries = []

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
            logger.info(f"Telegram bot connected: @{bot_info.get('username', '?')}")
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

            result = parse_command(chat_id, text)
            if isinstance(result, str):
                self._send_message(chat_id, result)
