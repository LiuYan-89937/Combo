from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import logging
from pathlib import Path
import sqlite3
import tempfile

from combo_service.config import get_settings
from combo_service.database import Database
from combo_service.oss_store import ObjectStore


LOGGER = logging.getLogger("combo_service.backup")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    database = Database(settings)
    database.initialize()
    now = datetime.now(timezone.utc)
    filename = f"combo_service-{now:%Y%m%dT%H%M%SZ}.sqlite3"
    object_key = f"{settings.backup_prefix}/{now:%Y/%m}/{filename}"
    with tempfile.TemporaryDirectory(prefix="combo-service-backup-") as temp_dir:
        backup_path = Path(temp_dir) / filename
        with database.connect() as source, sqlite3.connect(backup_path) as destination:
            source.backup(destination)
        digest = _file_sha256(backup_path)
        ObjectStore(settings).upload_backup(backup_path, object_key)
    LOGGER.info(
        "database backup uploaded detail=%s",
        json.dumps(
            {"object_key": object_key, "sha256": digest},
            separators=(",", ":"),
        ),
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
