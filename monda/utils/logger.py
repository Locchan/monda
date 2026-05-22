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
_file_handler: logging.FileHandler | None = None

loggers: dict[str, logging.Logger] = {}

default_level: int = logging.INFO


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


def setup_file_logging(path: str) -> None:
    global _file_handler
    if _file_handler is not None:
        return
    _file_handler = logging.FileHandler(path)
    _file_handler.setLevel(default_level)
    _file_handler.setFormatter(logging.Formatter(_log_format_full))
    for a_logger in loggers.values():
        a_logger.addHandler(_file_handler)


def get_logger(name: str = "MonDa", level: int | None = None) -> logging.Logger:
    global default_level
    if level is None:
        level = default_level
    if name in loggers:
        if loggers[name].level == level:
            return loggers[name]
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers = []
    logger.addHandler(_get_stdout_handler(level))
    if _file_handler is not None:
        _file_handler.setLevel(level)
        logger.addHandler(_file_handler)
    loggers[name] = logger
    return loggers[name]


def setdebug() -> None:
    global default_level
    get_logger().info("Enabling debug logging")
    default_level = logging.DEBUG
    get_logger().debug("Debug logging enabled")
