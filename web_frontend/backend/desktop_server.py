from __future__ import annotations

import os

import uvicorn

from web_frontend.backend.parent_process_watchdog import start_parent_process_watchdog


PORT_ENVIRONMENT_VARIABLE = "AGENTFACTORY_PORT"


def main() -> None:
    port = _runtime_port()
    server = uvicorn.Server(
        uvicorn.Config(
            "web_frontend.backend.event_api_server:app",
            host="127.0.0.1",
            port=port,
            log_level="info",
        )
    )
    start_parent_process_watchdog(lambda: setattr(server, "should_exit", True))
    server.run()


def _runtime_port() -> int:
    value = str(os.getenv(PORT_ENVIRONMENT_VARIABLE) or "").strip()
    if not value:
        raise RuntimeError(f"{PORT_ENVIRONMENT_VARIABLE} is required")
    port = int(value)
    if not 1 <= port <= 65_535:
        raise ValueError(f"{PORT_ENVIRONMENT_VARIABLE} must be a valid TCP port")
    return port


if __name__ == "__main__":
    main()
