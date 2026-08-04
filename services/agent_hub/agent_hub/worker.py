from __future__ import annotations

import json
import logging
import signal
import threading

from agent_hub.app_releases import AppReleaseRegistry
from agent_hub.config import get_settings
from agent_hub.database import Database
from agent_hub.oss_store import ObjectStore
from agent_hub.registry import AgentHubRegistry


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
    registry = AgentHubRegistry(settings, database, object_store)
    app_releases = AppReleaseRegistry(settings, database, object_store)
    stop = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("shutdown requested signal=%s", signum)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    recovered = registry.recover_stale_validation_jobs()
    recovered_app_releases = app_releases.recover_stale_jobs()
    LOGGER.info(
        "worker started recovered_validation_jobs=%s recovered_app_release_jobs=%s",
        recovered,
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
            job = registry.claim_validation_job()
            if job is None:
                stop.wait(settings.validation_poll_seconds)
                continue
            result = registry.validate_claimed_upload(str(job["upload_id"]))
            LOGGER.info("validation completed result=%s", json.dumps(result, ensure_ascii=False))
        except Exception:
            LOGGER.exception("validation loop failed")
            stop.wait(settings.validation_poll_seconds)
    LOGGER.info("validation worker stopped")


if __name__ == "__main__":
    main()
