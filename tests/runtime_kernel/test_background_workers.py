from __future__ import annotations

import unittest

from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager


class RuntimeBackgroundWorkerManagerTest(unittest.TestCase):
    def test_start_and_shutdown_are_idempotent(self) -> None:
        worker = _Worker()
        manager = RuntimeBackgroundWorkerManager([worker])

        first_start = manager.start_all()
        second_start = manager.start_all()
        shutdown = manager.shutdown_all()
        second_shutdown = manager.shutdown_all()

        self.assertEqual(worker.starts, 1)
        self.assertEqual(worker.shutdowns, 1)
        self.assertEqual(first_start[0].status, "completed")
        self.assertEqual(second_start[0].status, "skipped")
        self.assertEqual(shutdown[0].status, "completed")
        self.assertEqual(second_shutdown, [])

    def test_shutdown_uses_stop_when_shutdown_is_absent(self) -> None:
        worker = _StopOnlyWorker()
        manager = RuntimeBackgroundWorkerManager([worker])

        manager.start_all()
        shutdown = manager.shutdown_all()

        self.assertEqual(worker.starts, 1)
        self.assertEqual(worker.stops, 1)
        self.assertEqual(shutdown[0].status, "completed")

    def test_start_failure_reports_lifecycle_event(self) -> None:
        manager = RuntimeBackgroundWorkerManager([_FailingWorker()])

        events = manager.start_all()

        self.assertEqual(events[0].status, "failed")
        self.assertIn("RuntimeError", events[0].message)
        self.assertEqual(manager.started_workers, ())


class _Worker:
    def __init__(self) -> None:
        self.starts = 0
        self.shutdowns = 0

    def start(self) -> None:
        self.starts += 1

    def shutdown(self) -> None:
        self.shutdowns += 1


class _StopOnlyWorker:
    def __init__(self) -> None:
        self.starts = 0
        self.stops = 0

    def start(self) -> None:
        self.starts += 1

    def stop(self) -> None:
        self.stops += 1


class _FailingWorker:
    def start(self) -> None:
        raise RuntimeError("cannot start")


if __name__ == "__main__":
    unittest.main()
