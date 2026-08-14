from __future__ import annotations

import os
import sys
from collections.abc import Callable
from threading import Thread


PARENT_STDIN_WATCHDOG_ENV = "AGENTFACTORY_PARENT_STDIN_WATCHDOG"


def start_parent_process_watchdog(on_parent_exit: Callable[[], None]) -> None:
    if os.getenv(PARENT_STDIN_WATCHDOG_ENV) != "1":
        return
    Thread(
        target=_wait_for_parent_pipe_close,
        args=(on_parent_exit,),
        name="desktop-parent-watchdog",
        daemon=True,
    ).start()


def _wait_for_parent_pipe_close(on_parent_exit: Callable[[], None]) -> None:
    try:
        sys.stdin.buffer.read()
    except (AttributeError, OSError, ValueError):
        pass
    on_parent_exit()
