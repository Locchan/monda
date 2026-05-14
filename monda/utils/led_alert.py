import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

from monda.utils.logger import get_logger
from monda.utils.misc import read_config

logger = get_logger()


def send_alert(message: str, files: list[str] | None = None) -> None:
    """Hand an alert to the led integration if configured; otherwise stderr-fallback.

    led integration: writes <basedir>/alert_<ts>_<rand>.json with
        {"message": <msg>, "files": [<relative paths>...]}.
    Attached files are moved into <basedir> first so the paths in the JSON
    resolve relative to it. The JSON is written via .tmp + os.replace so a
    watcher never sees a half-written file.

    Fallback (no LED.BASEDIR in config): prints "Alert: <msg>" to stderr and
    deletes any attached files instead of leaking them.
    """
    files = files or []
    basedir = read_config().get("LED", {}).get("BASEDIR")

    if not basedir:
        print(f"Alert: {message}", file=sys.stderr)
        for path in files:
            try:
                os.remove(path)
            except OSError as e:
                logger.warning(f"Could not delete unattached alert file '{path}': {e}")
        return

    os.makedirs(basedir, exist_ok=True)

    relative_paths: list[str] = []
    for src in files:
        if not os.path.isfile(src):
            logger.warning(f"Alert attachment missing, skipping: {src}")
            continue
        dest_name = os.path.basename(src)
        dest = os.path.join(basedir, dest_name)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(dest_name)
            dest_name = f"{stem}_{uuid.uuid4().hex[:8]}{ext}"
            dest = os.path.join(basedir, dest_name)
        shutil.move(src, dest)
        relative_paths.append(dest_name)

    payload = {"message": message, "files": relative_paths}
    alert_name = f"alert_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
    final_path = os.path.join(basedir, alert_name)
    tmp_path = final_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, final_path)
    logger.info(f"Wrote led alert: {message}. Files: {relative_paths}.")
