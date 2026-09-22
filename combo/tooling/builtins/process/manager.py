from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import logging
import subprocess
import threading
import time
import uuid
from typing import Any, Callable, Mapping, TextIO

from combo.tooling.builtins.process.runtime import ShellRuntime
from combo.tooling.workspace_paths import resolve_workspace_path


_OUTPUT_BUFFER_LIMIT = 1_000_000
_DEFAULT_OUTPUT_CHARS = 12_000
_OUTPUT_OBSERVATION_INTERVAL_SECONDS = 0.1
_CANCELLATION_GRACE_SECONDS = 2


ProcessOutputObserver = Callable[[dict[str, Any]], None]
ProcessCancellationCheck = Callable[[], bool]
LOGGER = logging.getLogger(__name__)


class OutputBuffer:
    def __init__(self, *, limit: int = _OUTPUT_BUFFER_LIMIT) -> None:
        self._limit = limit
        self._chunks: list[str] = []
        self._size = 0
        self._truncated = False
        self._revision = 0
        self._lock = threading.RLock()

    def append(self, value: str) -> None:
        if not value:
            return
        with self._lock:
            self._revision += 1
            self._chunks.append(value)
            self._size += len(value)
            while self._size > self._limit and self._chunks:
                removed = self._chunks.pop(0)
                self._size -= len(removed)
                self._truncated = True

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def snapshot(self, *, max_chars: int) -> tuple[str, bool]:
        with self._lock:
            text = "".join(self._chunks)
            truncated = self._truncated
        if len(text) > max_chars:
            text = text[-max_chars:]
            truncated = True
        return text, truncated


@dataclass(slots=True)
class ManagedProcess:
    process_id: str
    command: str
    cwd: Path
    process: subprocess.Popen[str]
    shell_runtime: ShellRuntime
    started_at: float
    stdout: OutputBuffer = field(default_factory=OutputBuffer)
    stderr: OutputBuffer = field(default_factory=OutputBuffer)
    reader_threads: list[threading.Thread] = field(default_factory=list)
    stop_requested: bool = False
    finished_at: float | None = None
    completed_at: str | None = None
    terminal: threading.Event = field(default_factory=threading.Event)
    changed: threading.Condition = field(default_factory=threading.Condition)
    monitor: threading.Thread | None = None
    start_reported: threading.Event = field(default_factory=threading.Event)
    notify_completion: bool = False

    @property
    def output_revision(self) -> int:
        return self.stdout.revision + self.stderr.revision + int(self.terminal.is_set())

    def status(self) -> str:
        exit_code = self.process.poll()
        if exit_code is None:
            return "running"
        if self.stop_requested:
            return "stopped"
        if exit_code == 0:
            return "completed"
        return "failed"


class ProcessManager:
    def __init__(self, *, environment: Mapping[str, str], shell_runtime: ShellRuntime) -> None:
        self._lock = threading.RLock()
        self._processes: dict[str, ManagedProcess] = {}
        self._closed = False
        self._pending_completions: dict[str, tuple[ProcessOutputObserver, dict[str, Any]]] = {}
        self._environment = dict(environment)
        self._shell_runtime = shell_runtime

    @property
    def shell_runtime(self) -> ShellRuntime:
        return self._shell_runtime

    def start(
        self,
        *,
        command: str,
        cwd: Path,
        mode: str,
        max_output_chars: int = _DEFAULT_OUTPUT_CHARS,
        on_output: ProcessOutputObserver | None = None,
        on_completion: ProcessOutputObserver | None = None,
        cancellation_requested: ProcessCancellationCheck | None = None,
    ) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("process manager is closed")
        process_id = uuid.uuid4().hex
        shell_runtime = self._shell_runtime
        process = subprocess.Popen(
            shell_runtime.command_argv(command),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=shell_runtime.environment(self._environment),
            **shell_runtime.process_options(),
        )
        managed = ManagedProcess(
            process_id=process_id,
            command=command,
            cwd=cwd,
            process=process,
            shell_runtime=shell_runtime,
            started_at=time.monotonic(),
        )
        with self._lock:
            self._processes[process_id] = managed
        output_changed = threading.Event()
        self._start_reader(managed, "stdout", process.stdout, output_changed=output_changed)
        self._start_reader(managed, "stderr", process.stderr, output_changed=output_changed)
        managed.monitor = threading.Thread(
            target=self._watch_process,
            args=(managed, on_completion if mode == "background" else None, max_output_chars),
            name=f"tool-{process_id}-completion", daemon=True,
        )
        managed.monitor.start()
        if mode == "foreground":
            self._wait_until_terminal(
                managed,
                max_output_chars=max_output_chars,
                output_changed=output_changed,
                on_output=on_output,
                cancellation_requested=cancellation_requested,
            )
        output = self.snapshot(process_id=process_id, max_output_chars=max_output_chars)
        if mode == "background":
            if output["status"] != "running":
                managed.terminal.wait()
                output = self.snapshot(process_id=process_id, max_output_chars=max_output_chars)
            managed.notify_completion = output["status"] == "running"
            managed.start_reported.set()
        return output

    def snapshot(
        self,
        *,
        process_id: str,
        max_output_chars: int = _DEFAULT_OUTPUT_CHARS,
    ) -> dict[str, Any]:
        managed = self._get(process_id)
        with managed.changed:
            stdout, stdout_truncated = managed.stdout.snapshot(max_chars=max_output_chars)
            stderr, stderr_truncated = managed.stderr.snapshot(max_chars=max_output_chars)
            exit_code = managed.process.poll()
            return {
                "process_id": managed.process_id,
                "status": managed.status(),
                "command": managed.command,
                "shell": managed.shell_runtime.shell_id,
                "shell_executable": str(managed.shell_runtime.executable),
                "cwd": str(managed.cwd),
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "duration_ms": int(((managed.finished_at if managed.finished_at is not None else time.monotonic()) - managed.started_at) * 1000),
                "completed_at": managed.completed_at,
                "output_revision": managed.output_revision,
            }

    def stop(
        self,
        *,
        process_id: str,
        grace_seconds: int,
        max_output_chars: int = _DEFAULT_OUTPUT_CHARS,
    ) -> dict[str, Any]:
        managed = self._get(process_id)
        self._terminate(managed, grace_seconds=grace_seconds)
        return self.snapshot(process_id=process_id, max_output_chars=max_output_chars)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._pending_completions.clear()
            process_ids = list(self._processes)
        for process_id in process_ids:
            try:
                self.stop(
                    process_id=process_id,
                    grace_seconds=0,
                    max_output_chars=1,
                )
            except (KeyError, OSError, subprocess.SubprocessError):
                continue

    def _get(self, process_id: str) -> ManagedProcess:
        with self._lock:
            try:
                return self._processes[process_id]
            except KeyError as exc:
                raise KeyError(f"unknown process_id: {process_id}") from exc

    def _start_reader(
        self,
        managed: ManagedProcess,
        stream_name: str,
        stream: TextIO | None,
        *,
        output_changed: threading.Event,
    ) -> None:
        if stream is None:
            return
        buffer = managed.stdout if stream_name == "stdout" else managed.stderr
        thread = threading.Thread(
            target=_read_stream,
            args=(stream, buffer, output_changed, managed.changed),
            name=f"tool-{managed.process_id}-{stream_name}",
            daemon=True,
        )
        managed.reader_threads.append(thread)
        thread.start()

    def _wait_until_terminal(
        self,
        managed: ManagedProcess,
        *,
        max_output_chars: int,
        output_changed: threading.Event,
        on_output: ProcessOutputObserver | None,
        cancellation_requested: ProcessCancellationCheck | None,
    ) -> None:
        while not managed.terminal.is_set():
            if cancellation_requested is not None and cancellation_requested():
                self._terminate(managed, grace_seconds=_CANCELLATION_GRACE_SECONDS)
                break
            changed = output_changed.wait(timeout=_OUTPUT_OBSERVATION_INTERVAL_SECONDS)
            if changed:
                try:
                    managed.process.wait(timeout=_OUTPUT_OBSERVATION_INTERVAL_SECONDS)
                except subprocess.TimeoutExpired:
                    pass
                output_changed.clear()
                self._notify_output(managed, max_output_chars=max_output_chars, observer=on_output)
        if output_changed.is_set():
            output_changed.clear()
            self._notify_output(managed, max_output_chars=max_output_chars, observer=on_output)

    def wait_snapshot(
        self, *, process_id: str, wait_seconds: float = 0,
        after_revision: int | None = None,
        cancellation_requested: ProcessCancellationCheck | None = None,
    ) -> dict[str, Any]:
        managed = self._get(process_id)
        deadline = time.monotonic() + wait_seconds
        with managed.changed:
            while not managed.terminal.is_set():
                if after_revision is not None and managed.output_revision > after_revision:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0 or (cancellation_requested is not None and cancellation_requested()):
                    break
                managed.changed.wait(timeout=min(remaining, _OUTPUT_OBSERVATION_INTERVAL_SECONDS))
        return self.snapshot(process_id=process_id)

    def _watch_process(
        self, managed: ManagedProcess, observer: ProcessOutputObserver | None, max_chars: int,
    ) -> None:
        managed.process.wait()
        managed.finished_at = time.monotonic()
        managed.completed_at = datetime.now(timezone.utc).isoformat()
        for thread in managed.reader_threads:
            thread.join(timeout=_OUTPUT_OBSERVATION_INTERVAL_SECONDS)
        with managed.changed:
            managed.terminal.set()
            managed.changed.notify_all()
        if observer is not None:
            managed.start_reported.wait()
            if not managed.notify_completion:
                return
            output = self.snapshot(process_id=managed.process_id, max_output_chars=max_chars)
            with self._lock:
                if not self._closed:
                    self._pending_completions[managed.process_id] = (observer, output)

    def deliver_completions(self) -> None:
        """Retry unpersisted notifications through the runtime supervisor."""
        with self._lock:
            pending = tuple(self._pending_completions.items())
        for process_id, (observer, output) in pending:
            try:
                observer(output)
            except Exception:
                LOGGER.warning("process completion delivery failed: %s", process_id, exc_info=True)
                continue
            with self._lock:
                self._pending_completions.pop(process_id, None)

    def _terminate(self, managed: ManagedProcess, *, grace_seconds: int) -> None:
        if managed.process.poll() is not None:
            return
        managed.stop_requested = True
        managed.shell_runtime.terminate_tree(managed.process)
        try:
            managed.process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            managed.shell_runtime.kill_tree(managed.process)
            managed.process.wait()

    def _notify_output(
        self,
        managed: ManagedProcess,
        *,
        max_output_chars: int,
        observer: ProcessOutputObserver | None,
    ) -> None:
        if observer is None:
            return
        try:
            observer(self.snapshot(process_id=managed.process_id, max_output_chars=max_output_chars))
        except Exception:
            LOGGER.warning("shell output observer failed for process %s", managed.process_id, exc_info=True)


def _read_stream(
    stream: TextIO, buffer: OutputBuffer, output_changed: threading.Event,
    changed: threading.Condition,
) -> None:
    try:
        while True:
            chunk = stream.readline()
            if chunk == "":
                break
            with changed:
                buffer.append(chunk)
                output_changed.set()
                changed.notify_all()
    finally:
        stream.close()


@dataclass(frozen=True, slots=True)
class ProcessRuntimeResource:
    manager: ProcessManager
    root: Path
    on_completion: ProcessOutputObserver | None = None
    allow_external: bool = False
    allowed_roots: tuple[Path, ...] = ()
    read_only_paths: tuple[Path, ...] = ()

    def tool_resource_context(self) -> dict[str, Any]:
        return {
            "schema": "process_runtime_context.v1",
            "root": str(self.root),
            "allow_external": self.allow_external,
            "allowed_roots": [str(path) for path in self.allowed_roots],
            "read_only_paths": [str(path) for path in self.read_only_paths],
            "shell_id": self.manager.shell_runtime.shell_id,
            "shell_executable": str(self.manager.shell_runtime.executable),
        }


def process_runtime_boundary(resources: dict[str, Any]) -> tuple[Path, bool]:
    runtime = _process_context(resources)
    if isinstance(runtime, ProcessRuntimeResource):
        return runtime.root, runtime.allow_external
    return Path(str(runtime["root"])).resolve(), bool(runtime.get("allow_external", False))


def process_runtime_allowed_roots(resources: dict[str, Any]) -> tuple[Path, ...]:
    runtime = _process_context(resources)
    if isinstance(runtime, ProcessRuntimeResource):
        return runtime.allowed_roots
    values = runtime.get("allowed_roots", ())
    if not isinstance(values, list):
        raise ValueError("process runtime allowed_roots must be an array")
    return tuple(Path(str(value)).resolve() for value in values)


def resolve_cwd(
    *,
    cwd: str | None,
    root: Path,
    allow_external: bool,
    allowed_roots: tuple[Path, ...] = (),
) -> Path:
    value = cwd if cwd is not None and cwd.strip() else "."
    return resolve_workspace_path(
        value, root=root, allow_external=allow_external, allowed_roots=allowed_roots,
    )


def is_read_only_process_path(path: Path, *, root: Path, resources: dict[str, Any]) -> bool:
    runtime = _process_context(resources)
    values = (
        runtime.read_only_paths
        if isinstance(runtime, ProcessRuntimeResource)
        else tuple(Path(str(value)).resolve() for value in runtime.get("read_only_paths", ()))
    )
    for resolved in values:
        if path == resolved or resolved in path.parents:
            return True
    return False


def require_process_runtime(resources: dict[str, Any]) -> ProcessRuntimeResource:
    runtime = resources.get("process_runtime")
    if not isinstance(runtime, ProcessRuntimeResource):
        raise RuntimeError("owned process runtime resource is not configured")
    return runtime


def _process_context(resources: dict[str, Any]) -> ProcessRuntimeResource | dict[str, Any]:
    value = resources.get("process_runtime")
    if isinstance(value, ProcessRuntimeResource):
        return value
    if isinstance(value, dict) and value.get("schema") == "process_runtime_context.v1":
        return value
    raise RuntimeError("process runtime context is not configured")


def required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def bounded_int(arguments: dict[str, Any], key: str, *, default: int, minimum: int, maximum: int) -> int:
    value = arguments.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value
