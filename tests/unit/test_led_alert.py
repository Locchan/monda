import json
from pathlib import Path

from monda.utils.led_alert import send_alert


def test_send_alert_writes_json(led_dir: Path, cfg_path: Path):
    send_alert("hello from test", target="general")
    files = list(led_dir.glob("alert_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["message"] == "hello from test"
    assert payload["files"] == []


def test_send_alert_moves_attachments(led_dir: Path, tmp_path: Path):
    src = tmp_path / "shot.jpg"
    src.write_bytes(b"JPEG")
    send_alert("with file", target="general", files=[str(src)])
    assert not src.exists()
    alerts = list(led_dir.glob("alert_*.json"))
    assert len(alerts) == 1
    payload = json.loads(alerts[0].read_text(encoding="utf-8"))
    assert payload["files"] == ["shot.jpg"]
    assert (led_dir / "shot.jpg").exists()


def test_send_alert_missing_target_falls_back(capsys, rewrite_config):
    rewrite_config({
        "NAME": "t",
        "LED_TARGETS": {},
        "WORKER_CONFIG": {},
        "JOB_CONFIG": {},
    })
    send_alert("fallback", target="missing")
    err = capsys.readouterr().err
    assert "Alert: fallback" in err
