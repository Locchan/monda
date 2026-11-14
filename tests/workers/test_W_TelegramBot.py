from types import SimpleNamespace

import pytest

from monda.classes.workers.telegram.W_TelegramBot import W_TelegramBot, parse_command
from helpers import make_base_config, write_config_file, activate_config


def _camera_site_cfg(cfg_path, tmp_path):
    data = make_base_config(
        TELEGRAM={"BOT_TOKEN": "1:TEST", "CHAT_IDS": [42]},
        WORKER_CONFIG={"W_TelegramBot": {"monbot": {"INTERVAL": 5}}},
        JOB_CONFIG={"J_HikAlertSnap": {"ENABLED": True}, "J_HikAlertClip": {"ENABLED": True}},
        LED_TARGETS={"general": {"BASEDIR": str(tmp_path / "led")}},
    )
    (tmp_path / "led").mkdir(exist_ok=True)
    write_config_file(cfg_path, data)
    activate_config(cfg_path)


def test_initialize_requires_token(cfg_path, tmp_path, merge_worker):
    merge_worker("W_TelegramBot", "monbot", {"INTERVAL": 5})
    w = W_TelegramBot("monbot", 5)
    assert w.initialize() is False


def test_initialize_connects(cfg_path, tmp_path, monkeypatch):
    _camera_site_cfg(cfg_path, tmp_path)

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"result": {"username": "monbot"}}

    monkeypatch.setattr(
        "monda.classes.workers.telegram.W_TelegramBot.requests.get",
        lambda *a, **k: Resp(),
    )
    w = W_TelegramBot("monbot", 5)
    assert w.initialize() is True


def test_parse_help_and_unknown():
    assert "hik_sender" in parse_command(1, "/help").lower() or "/help" in parse_command(1, "/help")
    assert "Unknown" in parse_command(1, "/nope")


def test_get_updates_failure_returns_empty(cfg_path, tmp_path, monkeypatch):
    _camera_site_cfg(cfg_path, tmp_path)
    monkeypatch.setattr(
        "monda.classes.workers.telegram.W_TelegramBot.requests.get",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net")),
    )
    w = W_TelegramBot("monbot", 5)
    w._last_update_id = 0
    assert w._get_updates() == []
