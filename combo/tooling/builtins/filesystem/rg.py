from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import threading
from typing import Any

from combo.tooling.builtins.filesystem.common import (
    filesystem_allowed_roots,
    filesystem_boundary,
    filesystem_mounts,
    path_risk_result,
    positive_int,
    required_string,
    resolve_path,
    workspace_relative_path,
)
from combo.tooling.envelope import tool_envelope
from combo.tooling.execution_context import register_runtime_tool_cancellation


_IGNORED_GLOBS = (
    "!**/.git/**",
    "!**/.hg/**",
    "!**/.svn/**",
    "!**/.mypy_cache/**",
    "!**/.pytest_cache/**",
    "!**/.ruff_cache/**",
    "!**/__pycache__/**",
    "!**/node_modules/**",
    "!**/dist/**",
    "!**/build/**",
    "!**/target/**",
)
_MAX_RESULTS = 5_000
_MAX_LINE_CHARS = 4_000
_MAX_OUTPUT_CHARS = 500_000
_MAX_FILE_BYTES = 20_000_000


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    return path_risk_result(
        arguments,
        context,
        path_key="path",
        default_action="allow",
        sensitive_action="ask",
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = required_string(arguments, "action")
    if action not in {"files", "search"}:
        raise ValueError("action must be files or search")
    search_path = str(arguments.get("path") or ".")
    root, allow_external = filesystem_boundary(resources)
    mounts = filesystem_mounts(resources)
    target = resolve_path(
        path=search_path,
        root=root,
        allow_external=allow_external,
        allowed_roots=filesystem_allowed_roots(resources),
    )
    if not target.exists():
        raise FileNotFoundError(str(target))

    max_results = positive_int(arguments.get("max_results", 100), "max_results")
    if max_results > _MAX_RESULTS:
        raise ValueError(f"max_results must be less than or equal to {_MAX_RESULTS}")
    executable = _resolve_bundled_rg()
    if action == "files":
        argv = _files_argv(executable, arguments, target)
        return tool_envelope(
            _run_files(
                argv,
                cwd=target if target.is_dir() else target.parent,
                workspace_root=root,
                mounts=mounts,
                max_results=max_results,
            )
        )
    argv = _search_argv(executable, arguments, target)
    return tool_envelope(
        _run_search(
            argv,
            cwd=target if target.is_dir() else target.parent,
            search_target=target,
            workspace_root=root,
            mounts=mounts,
            max_results=max_results,
        )
    )


def _resolve_bundled_rg() -> Path:
    configured = os.getenv("COMBO_RG_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
    else:
        project_root = os.getenv("COMBO_PROJECT_ROOT", "").strip()
        if not project_root:
            raise RuntimeError(
                "bundled ripgrep location is unavailable: COMBO_PROJECT_ROOT is not configured"
            )
        resource_root = Path(project_root).expanduser().resolve()
        development_resources = resource_root / "src-tauri" / "resources"
        if development_resources.is_dir():
            resource_root = development_resources
        executable_name = "rg.exe" if os.name == "nt" else "rg"
        candidate = resource_root / "ripgrep" / executable_name
    if not candidate.is_file():
        raise RuntimeError(
            f"bundled ripgrep is missing at {candidate}; the application runtime is incomplete"
        )
    if os.name != "nt" and not os.access(candidate, os.X_OK):
        raise RuntimeError(f"bundled ripgrep is not executable: {candidate}")
    return candidate


def _files_argv(executable: Path, arguments: dict[str, Any], target: Path) -> list[str]:
    argv = [
        str(executable),
        "--files",
        "--color",
        "never",
        "--no-messages",
        "--sort",
        "path",
    ]
    _append_ignored_globs(argv)
    pattern = required_string(arguments, "pattern")
    argv.extend(("--glob", pattern))
    argv.append(_target_argument(target))
    return argv


def _search_argv(executable: Path, arguments: dict[str, Any], target: Path) -> list[str]:
    argv = [
        str(executable),
        "--json",
        "--color",
        "never",
        "--no-messages",
        "--sort",
        "path",
        "--max-filesize",
        str(_MAX_FILE_BYTES),
    ]
    _append_ignored_globs(argv)
    argv.extend(("--regexp", required_string(arguments, "pattern"), _target_argument(target)))
    return argv


def _append_ignored_globs(argv: list[str]) -> None:
    for pattern in _IGNORED_GLOBS:
        argv.extend(("--glob", pattern))


def _target_argument(target: Path) -> str:
    return target.name if target.is_file() else "."


def _run_files(
    argv: list[str],
    *,
    cwd: Path,
    workspace_root: Path,
    mounts: dict[str, Path],
    max_results: int,
) -> dict[str, Any]:
    files: list[dict[str, str]] = []
    output_chars = 0
    truncated = False
    with _RipgrepProcess(argv, cwd=cwd) as process:
        assert process.stdout is not None
        for raw_line in process.stdout:
            relative = raw_line.rstrip("\r\n")
            if not relative:
                continue
            if len(files) >= max_results:
                truncated = True
                process.stop()
                break
            absolute = (cwd / relative).resolve(strict=False)
            path = workspace_relative_path(
                absolute,
                workspace_root=workspace_root,
                mounts=mounts,
            )
            output_chars += len(path)
            if output_chars > _MAX_OUTPUT_CHARS:
                truncated = True
                process.stop()
                break
            files.append({"path": path})
            if len(files) == max_results:
                truncated = True
                process.stop()
                break
        exit_code, stderr = process.finish()
    _raise_for_exit(exit_code, stderr, argv, stopped=truncated)
    return {"files": files, "truncated": truncated}


def _run_search(
    argv: list[str],
    *,
    cwd: Path,
    search_target: Path,
    workspace_root: Path,
    mounts: dict[str, Path],
    max_results: int,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    output_chars = 0
    truncated = False
    with _RipgrepProcess(argv, cwd=cwd) as process:
        assert process.stdout is not None
        for raw_line in process.stdout:
            event = _json_event(raw_line)
            if event is None:
                continue
            event_type = event.get("type")
            if event_type != "match":
                continue
            data = event.get("data") or {}
            path = _event_path(data, cwd=cwd, search_target=search_target)
            line_number = int(data.get("line_number") or 0)
            text, text_truncated = _bounded_text(_event_text(data))
            if len(matches) >= max_results or output_chars > _MAX_OUTPUT_CHARS:
                truncated = True
                process.stop()
                break
            match = {
                "path": workspace_relative_path(
                    Path(path),
                    workspace_root=workspace_root,
                    mounts=mounts,
                ),
                "line_number": line_number,
                "text": text,
                "text_truncated": text_truncated,
            }
            matches.append(match)
            output_chars += len(match["path"]) + len(text)
            if len(matches) == max_results or output_chars > _MAX_OUTPUT_CHARS:
                truncated = True
                process.stop()
                break
        exit_code, stderr = process.finish()
    _raise_for_exit(exit_code, stderr, argv, stopped=truncated)
    return {"matches": matches, "truncated": truncated}


class _RipgrepProcess:
    def __init__(self, argv: list[str], *, cwd: Path) -> None:
        self._process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=os.name != "nt",
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
        )
        self.stdout = self._process.stdout
        self._result: tuple[int, str] | None = None
        self._lock = threading.Lock()
        self._unregister = register_runtime_tool_cancellation(self.stop)

    def __enter__(self) -> _RipgrepProcess:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if exc_type is not None:
                self.stop()
            self.finish()
        finally:
            self._unregister()

    def stop(self) -> None:
        with self._lock:
            if self._process.poll() is not None:
                return
            if os.name == "nt":
                self._process.kill()
                return
            try:
                os.killpg(self._process.pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            except OSError:
                self._process.kill()

    def finish(self) -> tuple[int, str]:
        if self._result is not None:
            return self._result
        if self.stdout is not None:
            self.stdout.close()
            self.stdout = None
        stderr = ""
        if self._process.stderr is not None:
            stderr = self._process.stderr.read()
            self._process.stderr.close()
        self._result = (self._process.wait(), stderr.strip())
        return self._result


def _raise_for_exit(
    exit_code: int,
    stderr: str,
    argv: list[str],
    *,
    stopped: bool,
) -> None:
    if stopped or exit_code in {0, 1}:
        return
    detail = stderr or f"exit code {exit_code}"
    raise RuntimeError(f"bundled ripgrep failed: {detail}; executable={argv[0]}")


def _json_event(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise RuntimeError("bundled ripgrep returned invalid JSON output") from exc
    return value if isinstance(value, dict) else None


def _event_path(data: dict[str, Any], *, cwd: Path, search_target: Path) -> str:
    value = data.get("path") or {}
    raw = value.get("text") if isinstance(value, dict) else None
    if isinstance(raw, str) and raw:
        return str((cwd / raw).resolve(strict=False))
    return str(search_target.resolve(strict=False))


def _event_text(data: dict[str, Any]) -> str:
    value = data.get("lines") or {}
    raw = value.get("text") if isinstance(value, dict) else ""
    return str(raw or "").rstrip("\r\n")


def _bounded_text(value: str) -> tuple[str, bool]:
    if len(value) <= _MAX_LINE_CHARS:
        return value, False
    return value[:_MAX_LINE_CHARS], True
