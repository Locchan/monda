from pathlib import Path

from helpers import activate_config, configs_dir, write_config_file
from monda.classes.jobs.hik.J_HikSnapArch import J_HikSnapArch


def _load(cfg_path, tmp_path):
    import json

    data = json.loads((configs_dir() / "camera_site.json").read_text(encoding="utf-8"))
    for name, tgt in data["LED_TARGETS"].items():
        p = tmp_path / f"led-{name}"
        p.mkdir(exist_ok=True)
        tgt["BASEDIR"] = str(p)
    write_config_file(cfg_path, data)
    activate_config(cfg_path)


def test_arch_empty_src(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    dest = tmp_path / "dest"
    j = J_HikSnapArch("arch", {"SRC_DIR": str(src), "DEST_DIR": str(dest)})
    assert j.initialize()
    j._work()
    assert list(dest.glob("*")) == []


def test_arch_missing_src(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    j = J_HikSnapArch("arch", {"SRC_DIR": str(tmp_path / "nope"), "DEST_DIR": str(tmp_path / "d")})
    j.initialize()
    j._work()  # no raise


def test_arch_creates_archive_and_clears_src(cfg_path, tmp_path):
    _load(cfg_path, tmp_path)
    src = tmp_path / "src"
    dest = tmp_path / "dest"
    src.mkdir()
    (src / "a.jpg").write_bytes(b"1")
    (src / "b.jpg").write_bytes(b"2")
    j = J_HikSnapArch("arch", {"SRC_DIR": str(src), "DEST_DIR": str(dest)})
    j.initialize()
    j._work()
    assert list(dest.glob("snap_*.tar.zst"))
    assert list(src.iterdir()) == []
