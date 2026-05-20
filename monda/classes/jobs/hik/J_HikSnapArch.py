import os
import shutil
import tarfile
import tempfile
from datetime import datetime

import zstandard

from monda.classes.base.Job import Job
from monda.utils.logger import get_logger

logger = get_logger()


class J_HikSnapArch(Job):

    job_class_name = "J_HikSnapArch"
    job_class_name_short = "J:HkArch"
    required_config_entries = ["SRC_DIR", "DEST_DIR"]

    def _initialize(self) -> bool:
        return True

    def _work(self) -> None:
        src_dir = self.config["SRC_DIR"]
        dest_dir = self.config["DEST_DIR"]

        if not os.path.isdir(src_dir):
            self._info(f"J_HikSnapArch: SRC_DIR '{src_dir}' does not exist, nothing to do.")
            return

        files = sorted(
            entry.name for entry in os.scandir(src_dir) if entry.is_file()
        )
        if not files:
            self._info(f"J_HikSnapArch: '{src_dir}' is empty, nothing to archive.")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_name = f"snap_{timestamp}.tar.zst"

        fd, archive_path = tempfile.mkstemp(suffix=".tar.zst", prefix="hikarch_")
        os.close(fd)
        try:
            with open(archive_path, "wb") as fh:
                with zstandard.ZstdCompressor().stream_writer(fh) as zst:
                    with tarfile.open(fileobj=zst, mode="w|") as tar:
                        for fname in files:
                            tar.add(os.path.join(src_dir, fname), arcname=fname)
        except Exception:
            os.unlink(archive_path)
            raise

        dest_path = os.path.join(dest_dir, archive_name)
        copy_ok = False
        try:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(archive_path, dest_path)
            copy_ok = True
        except OSError as e:
            logger.warning(f"J_HikSnapArch: copy to '{dest_path}' failed (NFS down?): {e}")

        try:
            os.unlink(archive_path)
        except OSError as e:
            logger.warning(f"J_HikSnapArch: could not remove temp archive '{archive_path}': {e}")

        if copy_ok:
            for fname in files:
                try:
                    os.unlink(os.path.join(src_dir, fname))
                except OSError as e:
                    logger.warning(f"J_HikSnapArch: could not remove '{fname}': {e}")
            self._info(f"J_HikSnapArch: archived {len(files)} file(s) to '{dest_path}'.")
        else:
            self._info(f"J_HikSnapArch: {len(files)} source file(s) retained until next run.")
