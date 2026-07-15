from __future__ import annotations

import signal
import threading


def main() -> int:
    stopped = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    stopped.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
