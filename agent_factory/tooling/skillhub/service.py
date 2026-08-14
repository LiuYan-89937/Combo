from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from threading import RLock
from typing import Any

from agent_factory.tooling.skillhub.search_query import normalize_skillhub_search_query
from agent_factory.dynamic_runtime.skill_source import normalize_staged_skill_package


SKILLHUB_COMMAND = "skillhub"
SKILLHUB_SKIP_SELF_UPGRADE_ENV = "SKILLHUB_SKIP_SELF_UPGRADE"
_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class SkillHubCommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def output(self) -> str:
        return "\n".join(part for part in (self.stdout.strip(), self.stderr.strip()) if part)


class SkillHubService:
    """External SkillHub source adapter publishing into the unified Skill pool."""

    def __init__(self, *, skills_dir: str | Path, command: str = SKILLHUB_COMMAND) -> None:
        self.skills_dir = Path(skills_dir).expanduser().resolve()
        self.command = command
        self._publish: Callable[[], None] | None = None
        self._lock = RLock()

    def bind_publisher(self, publish: Callable[[], None]) -> None:
        if self._publish is not None:
            raise RuntimeError("SkillHub publisher is already bound")
        self._publish = publish

    def status(self) -> dict[str, Any]:
        cli_path = resolve_skillhub_cli(self.command)
        return {
            "action": "status",
            "status": "ok" if cli_path else "missing",
            "message": "SkillHub CLI is available." if cli_path else "SkillHub CLI is not installed.",
            "cli_available": bool(cli_path),
            "cli_path": cli_path,
            "cli_version": _skillhub_cli_version(cli_path) if cli_path else "",
            "skills_dir": str(self.skills_dir),
            "items": [],
        }

    def search(self, query: str, *, timeout_seconds: int = 90) -> dict[str, Any]:
        normalized_query = normalize_skillhub_search_query(query)
        cli_path = self._require_cli()
        result = _run_skillhub_command(
            cli_path,
            ["search", normalized_query, "--json"],
            timeout_seconds=timeout_seconds,
        )
        if result.returncode != 0:
            raise RuntimeError(result.output or "SkillHub search failed")
        items = _search_items(result.stdout)
        return {
            **self.status(),
            "action": "search",
            "query": normalized_query,
            "message": f"SkillHub search completed with {len(items)} result(s).",
            "items": items,
            "raw_output": result.output[:4000],
        }

    def install(self, skill: str, *, timeout_seconds: int = 240) -> dict[str, Any]:
        requested = _required_skill_name(skill)
        cli_path = self._require_cli()
        self.skills_dir.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, tempfile.TemporaryDirectory(
            prefix=".skillhub-install-",
            dir=self.skills_dir.parent,
        ) as temporary_directory:
            staging = Path(temporary_directory)
            result = _run_skillhub_command(
                cli_path,
                ["install", requested, "--dir", str(staging)],
                timeout_seconds=timeout_seconds,
            )
            if result.returncode != 0:
                raise RuntimeError(result.output or f"SkillHub install failed: {requested}")
            source = normalize_staged_skill_package(_installed_skill_root(staging))
            target = self.skills_dir / source.name
            backup = self.skills_dir.parent / f".{source.name}.skillhub-backup"
            if backup.exists():
                raise RuntimeError(f"stale SkillHub installation backup exists: {backup}")
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            _require_regular_skill_tree(source)
            if target.exists():
                os.replace(target, backup)
            try:
                shutil.copytree(source, target, symlinks=False)
                self._publish_changes()
            except BaseException:
                shutil.rmtree(target, ignore_errors=True)
                if backup.exists():
                    os.replace(backup, target)
                self._publish_changes()
                raise
            shutil.rmtree(backup, ignore_errors=True)
        return {
            **self.status(),
            "action": "install",
            "message": f"Skill installed: {target.name}",
            "installed_skill": {
                "skill_id": target.name,
                "path": str(target),
                "source": "skillhub",
                "enabled": True,
            },
            "restart_required": False,
            "raw_output": result.output[:4000],
        }

    def remove(self, skill: str) -> dict[str, Any]:
        skill_name = _required_skill_name(skill)
        target = (self.skills_dir / skill_name).resolve()
        if target.parent != self.skills_dir:
            raise ValueError("SkillHub skill path escapes the managed Skill directory")
        with self._lock:
            if not target.is_dir():
                raise LookupError(f"installed Skill not found: {skill_name}")
            backup = self.skills_dir.parent / f".{skill_name}.skillhub-remove"
            if backup.exists():
                raise RuntimeError(f"stale SkillHub removal backup exists: {backup}")
            os.replace(target, backup)
            try:
                self._publish_changes()
            except BaseException:
                os.replace(backup, target)
                self._publish_changes()
                raise
            shutil.rmtree(backup)
        return {
            **self.status(),
            "action": "remove",
            "message": f"Skill removed: {skill_name}",
            "removed_skill": {"skill_id": skill_name, "path": str(target)},
            "restart_required": False,
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "status").strip().lower()
        if action == "status":
            return self.status()
        if action == "search":
            return self.search(str(payload.get("query") or ""))
        if action == "install":
            return self.install(str(payload.get("skill") or ""))
        if action == "remove":
            return self.remove(str(payload.get("skill") or ""))
        raise ValueError(f"unsupported SkillHub action: {action}")

    def _require_cli(self) -> str:
        cli_path = resolve_skillhub_cli(self.command)
        if cli_path is None:
            raise RuntimeError("SkillHub CLI is not installed")
        return cli_path

    def _publish_changes(self) -> None:
        if self._publish is None:
            raise RuntimeError("SkillHub capability publisher is not bound")
        self._publish()


def ensure_global_skillhub_cli() -> dict[str, Any]:
    """Report the external CLI state without creating a second Skill registry."""
    cli_path = resolve_skillhub_cli()
    return {
        "status": "ok" if cli_path else "missing",
        "cli_available": bool(cli_path),
        "cli_path": cli_path,
        "cli_version": _skillhub_cli_version(cli_path) if cli_path else "",
        "installed": False,
    }


def resolve_skillhub_cli(command: str = SKILLHUB_COMMAND) -> str | None:
    requested = str(command or "").strip()
    if not requested:
        return None
    discovered = shutil.which(requested)
    if discovered:
        return str(Path(discovered).expanduser().resolve())
    explicit = Path(requested).expanduser()
    if explicit.is_absolute() or explicit.parent != Path("."):
        return str(explicit.resolve()) if explicit.is_file() else None
    if requested != SKILLHUB_COMMAND:
        return None
    wrapper_names = ("skillhub.exe", "skillhub.cmd") if os.name == "nt" else ("skillhub",)
    for wrapper_name in wrapper_names:
        candidate = Path.home() / ".local" / "bin" / wrapper_name
        if candidate.is_file():
            return str(candidate.resolve())
    python_cli = Path.home() / ".skillhub" / "skills_store_cli.py"
    return str(python_cli.resolve()) if python_cli.is_file() else None


def _run_skillhub_command(
    cli_path: str,
    arguments: list[str],
    *,
    timeout_seconds: int,
) -> SkillHubCommandResult:
    path = Path(cli_path)
    command = [sys.executable, str(path), *arguments] if path.suffix.lower() == ".py" else [cli_path, *arguments]
    environment = os.environ.copy()
    environment[SKILLHUB_SKIP_SELF_UPGRADE_ENV] = "1"
    process = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_seconds,
        check=False,
        env=environment,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    return SkillHubCommandResult(
        returncode=int(process.returncode),
        stdout=process.stdout or "",
        stderr=process.stderr or "",
    )


def _skillhub_cli_version(cli_path: str | None) -> str:
    if cli_path is None:
        return ""
    version_files = (
        Path.home() / ".skillhub" / "version.json",
        Path(cli_path).parent / "version.json",
    )
    for version_file in version_files:
        if not version_file.is_file():
            continue
        try:
            payload = json.loads(version_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        version = str(payload.get("version") or "").strip() if isinstance(payload, dict) else ""
        if version:
            return f"skillhub {version}"
    return ""


def _installed_skill_root(staging: Path) -> Path:
    manifests = sorted(staging.rglob("SKILL.md"), key=lambda item: item.as_posix())
    roots = []
    for manifest in manifests:
        parent = manifest.parent.parent
        nested = False
        while parent != staging and staging in parent.parents:
            if (parent / "SKILL.md").is_file():
                nested = True
                break
            parent = parent.parent
        if not nested:
            roots.append(manifest.parent)
    if len(roots) != 1:
        raise RuntimeError("SkillHub installation must contain exactly one top-level SKILL.md")
    return roots[0]


def _require_regular_skill_tree(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"SkillHub Skill contains a symbolic link: {path.relative_to(root)}")
        if not path.is_file() and not path.is_dir():
            raise ValueError(f"SkillHub Skill contains an unsupported filesystem entry: {path.relative_to(root)}")


def _required_skill_name(value: str) -> str:
    skill = str(value or "").strip().split()[0] if str(value or "").strip() else ""
    if not _SKILL_NAME.fullmatch(skill):
        raise ValueError("SkillHub skill name is invalid")
    return skill


def _search_items(output: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        payload = None
    raw_items = (
        payload.get("results", payload.get("items"))
        if isinstance(payload, dict)
        else payload
    )
    if isinstance(raw_items, list):
        return [
            {
                "name": str(item.get("name") or item.get("displayName") or item.get("slug") or item.get("skill") or ""),
                "install_name": str(item.get("slug") or item.get("skill") or item.get("name") or ""),
                "version": str(item.get("version") or ""),
                "summary": str(item.get("summary") or item.get("description") or ""),
                "source": str(item.get("source") or "community"),
            }
            for item in raw_items
            if isinstance(item, dict) and str(item.get("slug") or item.get("skill") or item.get("name") or "").strip()
        ][:10]
    items: list[dict[str, Any]] = []
    for line in output.splitlines():
        text = line.strip().lstrip("-*0123456789. ")
        token = text.split(maxsplit=1)[0] if text else ""
        if not _SKILL_NAME.fullmatch(token) or token.casefold() in {"search", "version", "description"}:
            continue
        items.append({
            "name": token,
            "install_name": token,
            "version": "",
            "summary": text[len(token):].strip(" :-"),
            "source": "community",
        })
        if len(items) == 10:
            break
    return items
