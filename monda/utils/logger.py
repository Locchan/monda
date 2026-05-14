import io
import logging
import sys
import os
from os import W_OK

from monda.utils.globs import TERMINAL_POWERSHELL
_log_format = "%(asctime)s [%(levelname)-7s] [%(threadName)-20s] %(module)-14s:%(lineno)-4d | %(message)s"

TERM_FIXES_APPLIED = False

if os.name == 'nt' or not os.access("/var/log/", W_OK):
    log_path = "monda.log"
else:
    log_path = "/var/log/monda.log"

loggers = {}

default_level = logging.INFO


def detect_terminal():
    if os.getenv('PSModulePath', ''):
        return TERMINAL_POWERSHELL
    else:
        return True


def get_stream_handlers(level=logging.INFO):
    global TERM_FIXES_APPLIED

    if not TERM_FIXES_APPLIED:
        if detect_terminal() == TERMINAL_POWERSHELL:
            print("=== Powershell detected. Applying Windows terminal output fixes. ===")
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        TERM_FIXES_APPLIED = True

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(logging.Formatter(_log_format))

    stream_handler_file = logging.FileHandler(log_path)
    stream_handler_file.setLevel(level)
    stream_handler_file.setFormatter(logging.Formatter(_log_format))

    return stream_handler, stream_handler_file


def get_logger(name="MonDa", level=None):
    global default_level
    if level is None:
        level = default_level
    if name in loggers:
        if loggers[name].level == level:
            return loggers[name]
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers = []
    for ahandler in get_stream_handlers(level):
        logger.addHandler(ahandler)
    loggers[name] = logger
    return loggers[name]


def setdebug():
    global default_level
    get_logger().info("Enabling debug logging")
    default_level = logging.DEBUG
    get_logger().debug("Debug logging enabled")