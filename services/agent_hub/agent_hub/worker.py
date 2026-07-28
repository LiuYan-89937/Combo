from __future__ import annotations

import json
import logging
import signal
import threading

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
    registry = AgentHubRegistry(settings, database, ObjectStore(settings))
    stop = threading.Event()

    def request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("shutdown requested signal=%s", signum)
        stop.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    recovered = registry.recover_stale_validation_jobs()
    LOGGER.info("validation worker started recovered_jobs=%s", recovered)
    while not stop.is_set():
        try:
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
