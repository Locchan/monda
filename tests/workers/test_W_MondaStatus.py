import json
import socket
import sys
import urllib.request

from monda.classes.workers.W_MondaStatus import W_MondaStatus
from monda.utils import status

status_mod = sys.modules[W_MondaStatus.__module__]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_status_http_endpoint(merge_worker):
    port = _free_port()
    merge_worker("W_MondaStatus", "main", {"PORT": port, "INTERVAL": 10, "EDIT_MOTD": False})
    w = W_MondaStatus("main", 10)
    assert w.initialize() is True
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/status", timeout=2) as resp:
            data = json.loads(resp.read())
        assert data["status"] == "ok"
        assert "workers" in data
        w._work()
        assert str(port) in status.snapshot()["workers"]["W:Status_main"]["detail"]
    finally:
        w._server.shutdown()


def test_status_bind_failure(merge_worker, monkeypatch):
    merge_worker("W_MondaStatus", "main", {"PORT": 1, "INTERVAL": 10})

    def boom(*a, **k):
        raise OSError("permission denied")

    monkeypatch.setattr(status_mod, "_ReuseTCPServer", boom)
    w = W_MondaStatus("main", 10)
    assert w.initialize() is False
