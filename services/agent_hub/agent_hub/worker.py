from __future__ import annotations

import json
import logging
import signal
import threading

from agent_hub.app_releases import AppReleaseRegistry
from agent_hub.config import get_settings
from agent_hub.database import Database
from agent_hub.oss_store import ObjectStore


LOGGER = logging.getLogger("agent_hub.worker")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = get_settings()
    database = Database(settings)
    database.initialize()
    object_store = ObjectStore(settings)
    app_releases = AppReleaseRegistry(settings, database, object_store)
    stop = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("shutdown requested signal=%s", signum)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    recovered_app_releases = app_releases.recover_stale_jobs()
    LOGGER.info(
        "worker started recovered_app_release_jobs=%s",
        recovered_app_releases,
    )
    while not stop.is_set():
        try:
            app_release_job = app_releases.claim_job()
            if app_release_job is not None:
                result = app_releases.process_claimed_job(str(app_release_job["job_id"]))
                LOGGER.info(
                    "application release job completed result=%s",
                    json.dumps(result, ensure_ascii=False),
                )
                continue
            stop.wait(settings.worker_poll_seconds)
        except Exception:
            LOGGER.exception("application release worker loop failed")
            stop.wait(settings.worker_poll_seconds)
    LOGGER.info("application release worker stopped")


if __name__ == "__main__":
    main()
