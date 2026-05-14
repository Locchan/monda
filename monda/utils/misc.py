import json
import os
import signal

from art import text2art

CONFIG = {}


# This will read config only once on startup and then return this every time it is called.
#  Passing reload as True will force the function to actually re-read the config from disk.
def read_config(filepath=None, reload=False):
    global CONFIG

    if filepath is None:
        if "CFGFILE_PATH" in os.environ:
            filepath = os.environ["CFGFILE_PATH"]
        elif os.path.exists("config.json"):
            filepath = "config.json"
        elif os.path.exists("/etc/monda/config.json"):
            filepath = "/etc/monda/config.json"
        else:
            filepath = "config.json"

    if not os.path.exists(filepath):
        print(
            "Config file not found. Searched (in order):")
        print(
            "  1. CFGFILE_PATH environment variable")
        print(
            "  2. ./config.json")
        print(
            "  3. /etc/monda/config.json")
        print(f"Expected to find the config file at '{filepath}'")
        exit(1)
    if CONFIG == {} and not reload:
        with open(filepath, "r", encoding="utf-8") as config_file:
            try:
                CONFIG = json.load(config_file)
                if "DEBUG" in CONFIG and CONFIG["DEBUG"]:
                    print(f"Read config:\n{json.dumps(CONFIG, indent=2)}")
                return CONFIG
            except Exception as e:
                print(f"Could not read config file {filepath}: {e.__class__.__name__}")
                exit(1)
    else:
        return CONFIG


def write_config(data, filepath=None):
    if filepath is None:
        if "CFGFILE_PATH" in os.environ:
            filepath = os.environ["CFGFILE_PATH"]
        else:
            filepath = "config.json"
    # shutil.copyfile(filepath, filepath + f"{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}" + ".bak")
    with open(filepath, "w", encoding="utf-8") as config_file:
        json.dump(data, config_file, indent=2)
    read_config(filepath, reload=True)


def signal_stop(_signo, _stack_frame):
    from monda.utils.logger import get_logger
    logger = get_logger()
    logger.info(f"Caught {signal.Signals(_signo).name}. Shutting down...")
    os._exit(0)


def splash():
    from monda.utils.logger import get_logger
    logger = get_logger()
    splash_text = text2art("MonDa", font="Chunky")
    splash_text = splash_text.strip()
    lines = splash_text.split("\n")
    for aline in lines:
        logger.info(aline)
    logger.info("")
