import http.server
import json
import logging
import socketserver
import threading
import time
from datetime import datetime
from importlib.metadata import version, PackageNotFoundError

from monda.classes.base.Worker import Worker
from monda.utils.fmt import format_status_text
from monda.utils.logger import get_logger
from monda.utils import status as _status_mod

logger: logging.Logger = get_logger()

try:
    _VERSION = version("MonDa")
except PackageNotFoundError:
    _VERSION = "unknown"


def _make_handler(status_fn):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/status":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(status_fn(), indent=2).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    return _Handler


class _ReuseTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


# docs/workers.md
class W_MondaStatus(Worker):

    worker_class_name = "W_MondaStatus"
    worker_class_name_short = "W:Status"
    required_config_entries = ["PORT"]

    def _build_status(self) -> dict:
        snap = _status_mod.snapshot()
        return {
            "status": "ok",
            "version": _VERSION,
            "uptime_seconds": round(time.monotonic() - self._start_time, 1),
            "workers": snap["workers"],
            "jobs": snap["jobs"],
        }

    def _initialize(self) -> bool:
        port: int = self.config["PORT"]
        self._start_time: float = time.monotonic()
        self._motd_prefix: str = ""
        if self.config.get("EDIT_MOTD", False):
            motd_path: str = self.config.get("MOTD_FILE", "/etc/motd")
            try:
                with open(motd_path, "r", encoding="utf-8") as f:
                    self._motd_prefix = f.read()
            except OSError:
                pass
        try:
            self._server = _ReuseTCPServer(("", port), _make_handler(self._build_status))
        except OSError as e:
            logger.error(f"Cannot bind status server on port {port}: {e}")
            return False
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="W:Status_http",
        )
        self._server_thread.start()
        logger.info(f"Status endpoint listening on port {port}")
        self._update_status(f"HTTP on port {port}.")
        return True

    def _write_motd(self) -> None:
        if not self.config.get("EDIT_MOTD", False):
            return
        motd_path: str = self.config.get("MOTD_FILE", "/etc/motd")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        monda_section = f"\n--- MonDa status ({now}) ---\n{format_status_text(self._build_status())}"
        try:
            with open(motd_path, "w", encoding="utf-8") as f:
                f.write(self._motd_prefix + monda_section)
        except OSError as e:
            logger.warning(f"Could not write MOTD to {motd_path}: {e}")

    def _work(self) -> None:
        if not self._server_thread.is_alive():
            logger.warning("Status HTTP thread died, restarting.")
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                daemon=True,
                name="W:Status_http",
            )
            self._server_thread.start()
        self._write_motd()
