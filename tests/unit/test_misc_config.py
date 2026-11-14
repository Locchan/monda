import json
import time
from pathlib import Path

from helpers import activate_config, write_config_file
from monda.utils.misc import read_config, set_config_entry


def test_read_config_caches_until_mtime_changes(cfg_path: Path):
    c1 = read_config()
    c2 = read_config()
    assert c1 is c2 or c1 == c2
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    data["NAME"] = "changed"
    time.sleep(0.01)
    write_config_file(cfg_path, data)
    c3 = read_config()
    assert c3["NAME"] == "changed"


def test_set_config_entry(cfg_path: Path):
    set_config_entry("WORKER_CONFIG/W_MDWatcher/main", {"INTERVAL": 30})
    cfg = read_config()
    assert cfg["WORKER_CONFIG"]["W_MDWatcher"]["main"]["INTERVAL"] == 30


def test_fixture_configs_load(load_named_config):
    for name in ("minimal.json", "lab_site.json", "camera_site.json", "edge_site.json"):
        path = load_named_config(name)
        cfg = read_config()
        assert cfg.get("NAME")
        assert path.exists()
