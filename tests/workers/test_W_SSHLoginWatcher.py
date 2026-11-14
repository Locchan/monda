from pathlib import Path

import monda.classes.workers.W_SSHLoginWatcher as ssh_mod
from monda.classes.workers.W_SSHLoginWatcher import W_SSHLoginWatcher, _parse_syslog_line
from monda.utils import status


def test_parse_syslog_positive():
    line = "sshd[123]: Accepted publickey for alice from 10.0.0.5 port 22 ssh2"
    got = _parse_syslog_line(line)
    assert got is not None
    assert got[0] == "alice"
    assert got[1] == "10.0.0.5"


def test_parse_syslog_negative():
    assert _parse_syslog_line("sshd[1]: Failed password for root from 1.2.3.4") is None


def test_file_mode_alerts_on_new_login(tmp_path, merge_worker, led_dir):
    log = tmp_path / "auth.log"
    log.write_text("seed\n", encoding="utf-8")
    merge_worker(
        "W_SSHLoginWatcher",
        "main",
        {"INTERVAL": 10, "ALERT_TARGET": "general", "LOG_PATH": str(log)},
    )
    w = W_SSHLoginWatcher("main", 10)
    assert w.initialize() is True
    with log.open("a", encoding="utf-8") as f:
        f.write("sshd[9]: Accepted password for alice from 1.2.3.4 port 22 ssh2\n")
    w._work()
    assert list(led_dir.glob("alert_*.json"))
    assert "alice" in status.snapshot()["workers"]["W:SSHLogin_main"]["detail"]


def test_missing_log_file_mode(merge_worker, tmp_path):
    merge_worker("W_SSHLoginWatcher", "main", {"INTERVAL": 10, "LOG_PATH": str(tmp_path / "nope")})
    w = W_SSHLoginWatcher("main", 10)
    assert w.initialize() is True
    assert w._mode == "file"
