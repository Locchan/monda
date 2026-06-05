import io
import logging
import os
import sys

from monda.utils.globs import TERMINAL_POWERSHELL

_SYSTEMD: bool = os.getenv("INVOCATION_ID") is not None

_log_format_full: str = "%(asctime)s [%(levelname)-7s] [%(threadName)-20s] %(module)-14s:%(lineno)-4d | %(message)s"

_log_format_stdout: str
if _SYSTEMD:
    _log_format_stdout = "[%(levelname)-7s] [%(threadName)-20s] %(module)-14s:%(lineno)-4d | %(message)s"
    print("Systemd detected, altering log format.")
else:
    _log_format_stdout = _log_format_full

TERM_FIXES_APPLIED: bool = False
_log_dir: str | None = None
_entity_handler: logging.Handler | None = None

loggers: dict[str, logging.Logger] = {}

default_level: int = logging.INFO

DEFAULT_LOG_DIR: str = "/var/log/monda"


def detect_terminal() -> str | bool:
    if os.getenv('PSModulePath', ''):
        return TERMINAL_POWERSHELL
    else:
        return True


def _get_stdout_handler(level: int) -> logging.StreamHandler:
    global TERM_FIXES_APPLIED

    if not TERM_FIXES_APPLIED:
        if detect_terminal() == TERMINAL_POWERSHELL:
            print("=== Powershell detected. Applying Windows terminal output fixes. ===")
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        TERM_FIXES_APPLIED = True

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(_log_format_stdout))
    return handler


def resolve_log_dir(config: dict) -> str:
    if log_dir := config.get("LOG_DIR"):
        return log_dir
    if log_file := config.get("LOG_FILE"):
        base = os.path.dirname(log_file) or "/var/log"
        return os.path.join(base, "monda")
    return DEFAULT_LOG_DIR


def get_log_dir() -> str | None:
    return _log_dir


def log_path_for_thread(log_dir: str, thread_name: str) -> str:
    safe = thread_name.replace(":", "_")
    if thread_name.startswith("W:"):
        return os.path.join(log_dir, "workers", f"{safe}.log")
    if thread_name.startswith("J:"):
        return os.path.join(log_dir, "jobs", f"{safe}.log")
    return os.path.join(log_dir, "general.log")


class EntityFileHandler(logging.Handler):

    def __init__(self, log_dir: str) -> None:
        super().__init__(logging.DEBUG)
        self.log_dir = log_dir
        self._handlers: dict[str, logging.FileHandler] = {}
        self.setFormatter(logging.Formatter(_log_format_full))
        os.makedirs(os.path.join(log_dir, "workers"), exist_ok=True)
        os.makedirs(os.path.join(log_dir, "jobs"), exist_ok=True)

    def _get_file_handler(self, path: str) -> logging.FileHandler:
        if path not in self._handlers:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fh = logging.FileHandler(path)
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(self.formatter)
            self._handlers[path] = fh
        return self._handlers[path]

    def emit(self, record: logging.LogRecord) -> None:
        try:
            path = log_path_for_thread(self.log_dir, record.threadName)
            self._get_file_handler(path).emit(record)
        except Exception:
            self.handleError(record)


def setup_log_dir(log_dir: str) -> None:
    global _log_dir, _entity_handler
    if _log_dir is not None:
        return
    _log_dir = log_dir
    os.makedirs(log_dir, exist_ok=True)
    _entity_handler = EntityFileHandler(log_dir)
    for a_logger in loggers.values():
        a_logger.setLevel(logging.DEBUG)
        a_logger.addHandler(_entity_handler)


def list_log_files(category: str, log_dir: str | None = None) -> list[str]:
    log_dir = log_dir or _log_dir
    if log_dir is None:
        return []
    if category == "general":
        path = os.path.join(log_dir, "general.log")
        return [path] if os.path.isfile(path) else []
    subdir = os.path.join(log_dir, category)
    if not os.path.isdir(subdir):
        return []
    return sorted(
        os.path.join(subdir, name)
        for name in os.listdir(subdir)
        if name.endswith(".log")
    )


def _logger_level(stdout_level: int) -> int:
    if _entity_handler is not None:
        return logging.DEBUG
    return stdout_level


def get_logger(name: str = "MonDa", level: int | None = None) -> logging.Logger:
    global default_level
    if level is None:
        level = default_level
    if name in loggers:
        existing = loggers[name]
        if existing.level == _logger_level(level):
            for handler in existing.handlers:
                if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
                    handler.setLevel(level)
            return existing
    logger = logging.getLogger(name)
    logger.setLevel(_logger_level(level))
    logger.handlers = []
    logger.addHandler(_get_stdout_handler(level))
    if _entity_handler is not None:
        logger.addHandler(_entity_handler)
    loggers[name] = logger
    return loggers[name]


def setdebug() -> None:
    global default_level
    get_logger().info("Enabling debug logging")
    default_level = logging.DEBUG
    for a_logger in loggers.values():
        for handler in a_logger.handlers:
            if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
                handler.setLevel(logging.DEBUG)
    get_logger().debug("Debug logging enabled")
