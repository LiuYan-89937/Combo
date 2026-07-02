from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any
from urllib.request import Request, urlopen

from agent_factory.tooling.providers.skill import EnabledSkillConfig, EnabledSkillsConfig
from agent_factory.tooling.skills import parse_skill_directory


SKILLHUB_INSTALL_URL_ENV = "AGENTFACTORY_SKILLHUB_INSTALL_URL"
SKILLHUB_AUTO_INSTALL_ENV = "AGENTFACTORY_SKILLHUB_AUTO_INSTALL"
DEFAULT_SKILLHUB_INSTALL_URL = "https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/install/install.sh"
SKILLHUB_COMMAND = "skillhub"


@dataclass(frozen=True, slots=True)
class SkillHubCommandResult:
    returncode: int
    stdout: str
    stderr: str

    @property
    def combined_output(self) -> str:
        return "\n".join(item for item in (self.stdout.strip(), self.stderr.strip()) if item).strip()


class SkillHubService:
    def __init__(self, *, extension_root: str | Path, command: str = SKILLHUB_COMMAND) -> None:
        self.extension_root = Path(extension_root).expanduser().resolve()
        self.skills_dir = self.extension_root / "skills"
        self.command = command

    def status(self) -> dict[str, Any]:
        cli_path = shutil.which(self.command)
        version = ""
        if cli_path:
            result = _run_command([self.command, "--version"], timeout_seconds=15)
            version = result.combined_output
        return {
            "action": "status",
            "status": "ok" if cli_path else "missing",
            "message": "SkillHUB CLI is available." if cli_path else "SkillHUB CLI is not installed.",
            "cli_available": bool(cli_path),
            "cli_path": cli_path,
            "cli_version": version,
            "extension_root": str(self.extension_root),
            "skills_dir": str(self.skills_dir),
            "items": [],
            "raw_output": version,
            "installed_skill": None,
            "restart_required": False,
        }

    def search(self, query: str, *, timeout_seconds: int = 60) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            raise ValueError("skillhub search requires query")
        self._require_cli()
        result = _run_command([self.command, "search", query], timeout_seconds=timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(result.combined_output or f"skillhub search failed with exit code {result.returncode}")
        raw_output = result.combined_output
        return {
            "action": "search",
            "status": "ok",
            "message": "SkillHUB search completed.",
            "cli_available": True,
            "cli_path": shutil.which(self.command),
            "cli_version": self.status().get("cli_version") or "",
            "extension_root": str(self.extension_root),
            "skills_dir": str(self.skills_dir),
            "items": _search_items(raw_output),
            "raw_output": raw_output,
            "installed_skill": None,
            "restart_required": False,
        }

    def install(self, skill: str, *, timeout_seconds: int = 180) -> dict[str, Any]:
        skill = str(skill or "").strip()
        if not skill:
            raise ValueError("skillhub install requires skill")
        self._require_cli()
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        before = _skill_dir_snapshots(self.skills_dir)
        result = _run_command(
            [self.command, "install", skill, "--dir", str(self.skills_dir)],
            timeout_seconds=timeout_seconds,
        )
        if result.returncode != 0:
            raise RuntimeError(result.combined_output or f"skillhub install failed with exit code {result.returncode}")
        installed = self._resolve_installed_skill(skill, before)
        enabled_skill = self._enable_skill(installed)
        raw_output = result.combined_output
        return {
            "action": "install",
            "status": "ok",
            "message": f"Skill installed and enabled: {enabled_skill.skill_id}",
            "cli_available": True,
            "cli_path": shutil.which(self.command),
            "cli_version": self.status().get("cli_version") or "",
            "extension_root": str(self.extension_root),
            "skills_dir": str(self.skills_dir),
            "items": [],
            "raw_output": raw_output,
            "installed_skill": {
                "skill_id": enabled_skill.skill_id,
                "path": enabled_skill.path,
                "source": enabled_skill.source,
                "enabled": enabled_skill.enabled,
            },
            "restart_required": True,
        }

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        action = str(payload.get("action") or "status").strip().lower()
        if action == "status":
            return self.status()
        if action == "search":
            return self.search(str(payload.get("query") or ""))
        if action == "install":
            return self.install(str(payload.get("skill") or payload.get("query") or ""))
        raise ValueError(f"unsupported skillhub action: {action}")

    def tool_resource_summary(self) -> dict[str, Any]:
        return {
            "extension_root": str(self.extension_root),
            "skills_dir": str(self.skills_dir),
            "mode": "direct",
        }

    def _require_cli(self) -> None:
        if shutil.which(self.command):
            return
        raise RuntimeError("SkillHUB CLI is not installed. Start the web backend once or install skillhub globally.")

    def _resolve_installed_skill(self, requested: str, before: dict[str, float]) -> Path:
        candidates = _changed_skill_dirs(self.skills_dir, before)
        if not candidates:
            requested_dir = self.skills_dir / requested
            if requested_dir.is_dir():
                candidates = [requested_dir]
        parsed: list[tuple[Path, str]] = []
        for candidate in candidates:
            try:
                package = parse_skill_directory(candidate)
            except Exception:
                continue
            parsed.append((candidate, package.name))
        if len(parsed) == 1:
            return parsed[0][0]
        normalized_requested = _normalize_skill_name(requested)
        for candidate, skill_id in parsed:
            if skill_id == normalized_requested or candidate.name == normalized_requested:
                return candidate
        if parsed:
            return parsed[0][0]
        for child in sorted(self.skills_dir.iterdir() if self.skills_dir.is_dir() else []):
            if not child.is_dir():
                continue
            try:
                package = parse_skill_directory(child)
            except Exception:
                continue
            if package.name == normalized_requested or child.name == normalized_requested:
                return child
        raise RuntimeError("SkillHUB install completed but no valid SKILL.md was found in the target skills directory.")

    def _enable_skill(self, skill_root: Path) -> EnabledSkillConfig:
        package = parse_skill_directory(skill_root)
        relative_path = skill_root.relative_to(self.extension_root).as_posix()
        skill = EnabledSkillConfig(
            skill_id=package.name,
            enabled=True,
            source="skillhub",
            path=relative_path,
        )
        config = _load_enabled_skills(self.extension_root)
        skills = [item for item in config.skills if item.skill_id != skill.skill_id]
        skills.append(skill)
        _write_enabled_skills(
            self.extension_root,
            config.model_copy(update={"skills": sorted(skills, key=lambda item: item.skill_id)}),
        )
        return skill


def ensure_global_skillhub_cli(*, auto_install: bool = True, timeout_seconds: int = 180) -> dict[str, Any]:
    cli_path = shutil.which(SKILLHUB_COMMAND)
    if cli_path:
        version = _run_command([SKILLHUB_COMMAND, "--version"], timeout_seconds=15).combined_output
        return {
            "status": "ok",
            "cli_available": True,
            "cli_path": cli_path,
            "cli_version": version,
            "installed": False,
        }
    if not auto_install or not _auto_install_enabled():
        return {
            "status": "missing",
            "cli_available": False,
            "cli_path": None,
            "cli_version": "",
            "installed": False,
        }
    script = _download_install_script(timeout_seconds=timeout_seconds)
    try:
        result = _run_command(["bash", str(script), "--cli-only"], timeout_seconds=timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError(result.combined_output or f"SkillHUB installer exited with {result.returncode}")
    finally:
        try:
            script.unlink()
        except FileNotFoundError:
            pass
    cli_path = shutil.which(SKILLHUB_COMMAND)
    return {
        "status": "ok" if cli_path else "missing",
        "cli_available": bool(cli_path),
        "cli_path": cli_path,
        "cli_version": _run_command([SKILLHUB_COMMAND, "--version"], timeout_seconds=15).combined_output if cli_path else "",
        "installed": bool(cli_path),
    }


def _load_enabled_skills(extension_root: Path) -> EnabledSkillsConfig:
    path = extension_root / "enabled_skills.json"
    if not path.is_file():
        return EnabledSkillsConfig()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"enabled_skills.json must contain an object: {path}")
    return EnabledSkillsConfig.model_validate(payload)


def _write_enabled_skills(extension_root: Path, config: EnabledSkillsConfig) -> None:
    extension_root.mkdir(parents=True, exist_ok=True)
    path = extension_root / "enabled_skills.json"
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(config.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _run_command(command: list[str], *, timeout_seconds: int) -> SkillHubCommandResult:
    process = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    return SkillHubCommandResult(
        returncode=int(process.returncode),
        stdout=process.stdout or "",
        stderr=process.stderr or "",
    )


def _download_install_script(*, timeout_seconds: int) -> Path:
    url = os.getenv(SKILLHUB_INSTALL_URL_ENV, DEFAULT_SKILLHUB_INSTALL_URL).strip()
    request = Request(url, headers={"User-Agent": "FastAgentFactory/SkillHUB"})
    with urlopen(request, timeout=timeout_seconds) as response:
        content = response.read()
    target = Path(tempfile.gettempdir()) / f"agentfactory-skillhub-install-{os.getpid()}.sh"
    target.write_bytes(content)
    return target


def _auto_install_enabled() -> bool:
    value = os.getenv(SKILLHUB_AUTO_INSTALL_ENV)
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _skill_dir_snapshots(skills_dir: Path) -> dict[str, float]:
    if not skills_dir.is_dir():
        return {}
    result: dict[str, float] = {}
    for child in skills_dir.iterdir():
        if child.is_dir():
            result[child.name] = _latest_mtime(child)
    return result


def _changed_skill_dirs(skills_dir: Path, before: dict[str, float]) -> list[Path]:
    if not skills_dir.is_dir():
        return []
    changed: list[Path] = []
    for child in skills_dir.iterdir():
        if not child.is_dir():
            continue
        previous = before.get(child.name)
        current = _latest_mtime(child)
        if previous is None or current > previous:
            changed.append(child)
    return sorted(changed, key=lambda path: path.name)


def _latest_mtime(path: Path) -> float:
    latest = path.stat().st_mtime
    for child in path.rglob("*"):
        try:
            latest = max(latest, child.stat().st_mtime)
        except OSError:
            continue
    return latest


def _search_items(raw_output: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for line in raw_output.splitlines():
        text = line.strip()
        if not text:
            continue
        items.append({"name": _line_name(text), "summary": text, "raw": text})
    return items


def _line_name(text: str) -> str:
    cleaned = text.strip().lstrip("-*0123456789. \t")
    if not cleaned:
        return text
    return cleaned.split()[0].strip("：:|")


def _normalize_skill_name(value: str) -> str:
    return value.strip().lower().replace("_", "-")
