from __future__ import annotations

from collections import deque
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


_MAX_BUFFER_LINES = 5000
_PROCESS_STORE: dict[str, "_ManagedProcess"] = {}
_PROCESS_STORE_LOCK = threading.Lock()


class _ManagedProcess:
    def __init__(self, *, command: list[str], cwd: str | None, process: subprocess.Popen[str]) -> None:
        self.command = command
        self.cwd = cwd
        self.process = process
        self.started_at = time.time()
        self.stdout: deque[str] = deque(maxlen=_MAX_BUFFER_LINES)
        self.stderr: deque[str] = deque(maxlen=_MAX_BUFFER_LINES)
        self.lock = threading.Lock()

    def append_stdout(self, text: str) -> None:
        with self.lock:
            self.stdout.append(text)

    def append_stderr(self, text: str) -> None:
        with self.lock:
            self.stderr.append(text)

    def snapshot(self) -> dict[str, Any]:
        exit_code = self.process.poll()
        with self.lock:
            stdout = "".join(self.stdout)
            stderr = "".join(self.stderr)
        return {
            "command": self.command,
            "cwd": self.cwd,
            "pid": self.process.pid,
            "status": "running" if exit_code is None else "completed",
            "exit_code": exit_code,
            "started_at": self.started_at,
            "duration_ms": int((time.time() - self.started_at) * 1000),
            "stdout": stdout,
            "stderr": stderr,
        }


@tool("shell_run", parse_docstring=True)
def run_command(
    command: list[str],
    cwd: str | None = None,
    timeout_seconds: int = 60,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a command without shell expansion and return stdout, stderr, and exit code.

    Use this for safe command execution when arguments can be passed as a list.

    Args:
        command: Command and arguments as a list, for example ["python", "--version"].
        cwd: Optional working directory for the command.
        timeout_seconds: Maximum runtime before the command is stopped.
        env: Optional environment variables to add or override.
    """

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(cwd).expanduser()) if cwd else None,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        status = "completed"
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        exit_code = None
        stdout = _safe_text(exc.stdout)
        stderr = _safe_text(exc.stderr)
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "command": command,
        "cwd": cwd,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout[:20000],
        "stderr": stderr[:20000],
        "stdout_truncated": len(stdout) > 20000,
        "stderr_truncated": len(stderr) > 20000,
    }


@tool("shell_run_text", parse_docstring=True)
def run_shell_text(
    command: str,
    cwd: str | None = None,
    timeout_seconds: int = 60,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run a shell command string when shell syntax is required.

    Use this only when pipes, redirects, shell operators, or compound shell syntax are necessary.

    Args:
        command: Shell command string to execute.
        cwd: Optional working directory for the command.
        timeout_seconds: Maximum runtime before the command is stopped.
        env: Optional environment variables to add or override.
    """

    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=str(Path(cwd).expanduser()) if cwd else None,
            env={**os.environ, **(env or {})},
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=True,
        )
        status = "completed"
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        exit_code = None
        stdout = _safe_text(exc.stdout)
        stderr = _safe_text(exc.stderr)
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "command": command,
        "cwd": cwd,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout[:20000],
        "stderr": stderr[:20000],
        "stdout_truncated": len(stdout) > 20000,
        "stderr_truncated": len(stderr) > 20000,
    }


@tool("shell_which", parse_docstring=True)
def which_command(command: str) -> dict[str, Any]:
    """Resolve an executable command on PATH.

    Use this to check whether a command is available before trying to run it.

    Args:
        command: Executable name to resolve.
    """

    resolved = shutil.which(command)
    return {"command": command, "found": resolved is not None, "path": resolved}


@tool("shell_cwd", parse_docstring=True)
def current_working_directory() -> dict[str, str]:
    """Return the current working directory for the running process."""

    return {"cwd": os.getcwd()}


@tool("shell_env", parse_docstring=True)
def read_environment(names: list[str], include_values: bool = False) -> dict[str, Any]:
    """Check environment variables without revealing values unless explicitly requested.

    Use this to verify configuration presence without leaking secrets.

    Args:
        names: Environment variable names to inspect.
        include_values: Include raw values when explicitly needed.
    """

    values: dict[str, Any] = {}
    for name in names:
        exists = name in os.environ
        item: dict[str, Any] = {"exists": exists}
        if include_values and exists:
            item["value"] = os.environ[name]
        values[name] = item
    return {"variables": values}


@tool("shell_start", parse_docstring=True)
def start_command(
    command: list[str],
    cwd: str | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Start a long-running command asynchronously and return a process id.

    Use this when a command may keep running and needs later inspection instead of blocking
    the agent until it exits.

    Args:
        command: Command and arguments as a list, for example ["npm", "run", "dev"].
        cwd: Optional working directory for the command.
        env: Optional environment variables to add or override.
    """

    process = subprocess.Popen(
        command,
        cwd=str(Path(cwd).expanduser()) if cwd else None,
        env={**os.environ, **(env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    managed = _ManagedProcess(command=command, cwd=cwd, process=process)
    process_id = uuid.uuid4().hex
    with _PROCESS_STORE_LOCK:
        _PROCESS_STORE[process_id] = managed
    _start_reader_thread(process.stdout, managed.append_stdout)
    _start_reader_thread(process.stderr, managed.append_stderr)
    return {
        "process_id": process_id,
        "pid": process.pid,
        "command": command,
        "cwd": cwd,
        "status": "running",
    }


@tool("shell_status", parse_docstring=True)
def process_status(process_id: str, max_output_chars: int = 20000) -> dict[str, Any]:
    """Inspect an asynchronous shell process and return current buffered output.

    Use this after shell_start to observe whether a long-running command is still active
    and what it has printed so far.

    Args:
        process_id: Process id returned by shell_start.
        max_output_chars: Maximum stdout and stderr characters to return.
    """

    managed = _get_process(process_id)
    if managed is None:
        return {"process_id": process_id, "found": False}
    snapshot = managed.snapshot()
    stdout = snapshot["stdout"]
    stderr = snapshot["stderr"]
    return {
        "process_id": process_id,
        "found": True,
        **{key: value for key, value in snapshot.items() if key not in {"stdout", "stderr"}},
        "stdout": stdout[-max_output_chars:],
        "stderr": stderr[-max_output_chars:],
        "stdout_truncated": len(stdout) > max_output_chars,
        "stderr_truncated": len(stderr) > max_output_chars,
    }


@tool("shell_grep_process", parse_docstring=True)
def grep_process_output(
    process_id: str,
    pattern: str,
    stream: str = "both",
    case_sensitive: bool = False,
    max_matches: int = 100,
) -> dict[str, Any]:
    """Search buffered output from an asynchronous shell process.

    Use this to inspect long-running process logs for errors, URLs, readiness messages,
    warnings, or any other text without waiting for the process to finish.

    Args:
        process_id: Process id returned by shell_start.
        pattern: Text pattern to search for.
        stream: Which output stream to search: stdout, stderr, or both.
        case_sensitive: Match case exactly when true.
        max_matches: Maximum number of matches to return.
    """

    managed = _get_process(process_id)
    if managed is None:
        return {"process_id": process_id, "found": False, "matches": []}
    snapshot = managed.snapshot()
    streams = _selected_streams(snapshot, stream)
    matches: list[dict[str, Any]] = []
    needle = pattern if case_sensitive else pattern.lower()
    for stream_name, text in streams.items():
        for line_number, line in enumerate(text.splitlines(), start=1):
            haystack = line if case_sensitive else line.lower()
            if needle in haystack:
                matches.append({"stream": stream_name, "line": line_number, "text": line})
                if len(matches) >= max_matches:
                    return {
                        "process_id": process_id,
                        "found": True,
                        "pattern": pattern,
                        "matches": matches,
                        "truncated": True,
                    }
    return {
        "process_id": process_id,
        "found": True,
        "pattern": pattern,
        "matches": matches,
        "truncated": False,
    }


@tool("shell_stop", parse_docstring=True)
def stop_process(process_id: str, timeout_seconds: int = 5) -> dict[str, Any]:
    """Stop an asynchronous shell process started by shell_start.

    Use this when a long-running command is no longer needed or must be terminated.

    Args:
        process_id: Process id returned by shell_start.
        timeout_seconds: Seconds to wait after terminate before killing the process.
    """

    managed = _get_process(process_id)
    if managed is None:
        return {"process_id": process_id, "found": False, "status": "missing"}
    if managed.process.poll() is None:
        managed.process.terminate()
        try:
            managed.process.wait(timeout=timeout_seconds)
            status = "terminated"
        except subprocess.TimeoutExpired:
            managed.process.kill()
            managed.process.wait(timeout=timeout_seconds)
            status = "killed"
    else:
        status = "already_completed"
    return {
        "process_id": process_id,
        "found": True,
        "status": status,
        "exit_code": managed.process.poll(),
    }


def _safe_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value


def _start_reader_thread(stream, append) -> None:
    if stream is None:
        return

    def read_stream() -> None:
        for line in stream:
            append(line)

    thread = threading.Thread(target=read_stream, daemon=True)
    thread.start()


def _get_process(process_id: str) -> _ManagedProcess | None:
    with _PROCESS_STORE_LOCK:
        return _PROCESS_STORE.get(process_id)


def _selected_streams(snapshot: dict[str, Any], stream: str) -> dict[str, str]:
    if stream == "stdout":
        return {"stdout": snapshot["stdout"]}
    if stream == "stderr":
        return {"stderr": snapshot["stderr"]}
    return {"stdout": snapshot["stdout"], "stderr": snapshot["stderr"]}


SHELL_TOOLS = [
    run_command,
    run_shell_text,
    which_command,
    current_working_directory,
    read_environment,
    start_command,
    process_status,
    grep_process_output,
    stop_process,
]
