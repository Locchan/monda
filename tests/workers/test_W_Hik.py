from datetime import datetime, timedelta, timezone

import pytest

from helpers import activate_config, configs_dir, write_config_file
from monda.classes.base.hik.HikEvent import HikEvent
from monda.classes.workers import HikEvents, is_ignored_event
from monda.classes.workers.hik.W_HikConsumer import W_HikConsumer, camera_silenced
from monda.classes.workers.hik.W_HikProducer import W_HikProducer


def _load_camera_site(cfg_path, tmp_path):
    import json

    data = json.loads((configs_dir() / "camera_site.json").read_text(encoding="utf-8"))
    for name, tgt in data["LED_TARGETS"].items():
        p = tmp_path / f"led-{name}"
        p.mkdir(exist_ok=True)
        tgt["BASEDIR"] = str(p)
    write_config_file(cfg_path, data)
    activate_config(cfg_path)


def test_is_ignored_event(cfg_path, tmp_path):
    _load_camera_site(cfg_path, tmp_path)
    assert is_ignored_event("videoloss", "inactive") is True
    assert is_ignored_event("videoloss", "active") is False
    assert is_ignored_event("VMD", "active") is False


def test_producer_initialize_ok(cfg_path, tmp_path):
    _load_camera_site(cfg_path, tmp_path)
    w = W_HikProducer("cam4", 30)
    assert w.initialize() is True


def test_producer_initialize_bad_device(cfg_path, tmp_path, merge_worker):
    _load_camera_site(cfg_path, tmp_path)
    merge_worker("W_HikProducer", "bad", {"DEVICE": "nope", "INTERVAL": 30})
    w = W_HikProducer("bad", 30)
    with pytest.raises(RuntimeError, match="not found"):
        w.initialize()


def test_producer_process_alert_enqueues(cfg_path, tmp_path):
    _load_camera_site(cfg_path, tmp_path)
    HikEvents.clear()
    w = W_HikProducer("cam4", 30)
    w.initialize()
    w._use_redis = False
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<EventNotificationAlert xmlns="http://www.hikvision.com/ver20/XMLSchema">
  <eventType>VMD</eventType>
  <eventState>active</eventState>
  <dateTime>2026-01-01T12:00:00</dateTime>
</EventNotificationAlert>"""
    w.process_alert(xml)
    assert len(HikEvents) == 1
    assert HikEvents[0].name == "VMD"


def test_camera_silenced(cfg_path, tmp_path):
    _load_camera_site(cfg_path, tmp_path)
    until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    import json

    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["HIK_CONFIG"]["SILENCED"] = {"cam4": until}
    write_config_file(cfg_path, data)
    activate_config(cfg_path)
    assert camera_silenced("cam4") is True
    assert camera_silenced("cam1") is False


def test_consumer_unknown_event_alerts(cfg_path, tmp_path):
    _load_camera_site(cfg_path, tmp_path)
    w = W_HikConsumer("consumer", 1)
    assert w.initialize() is True
    event = HikEvent(
        name="Weird",
        state="active",
        date="2026-01-01T12:00:00",
        source="cam4",
    )
    w.process_event(event)
    from pathlib import Path

    general = Path(
        __import__("json").loads(cfg_path.read_text())["LED_TARGETS"]["general"]["BASEDIR"]
    )
    assert list(general.glob("alert_*.json"))
