from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
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
SEARCH_RESULT_LIMIT = 10
RAW_OUTPUT_PREVIEW_CHARS = 1200
SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
NAME_VERSION_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]{0,127}?)[\s@-]?v(?P<version>\d+(?:\.\d+){1,3}(?:[-+.\w]*)?)$",
    re.IGNORECASE,
)


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
        items = _search_items(raw_output, query=query, limit=SEARCH_RESULT_LIMIT)
        return {
            "action": "search",
            "status": "ok",
            "message": f"SkillHUB search completed. {len(items)} candidates returned.",
            "cli_available": True,
            "cli_path": shutil.which(self.command),
            "cli_version": self.status().get("cli_version") or "",
            "extension_root": str(self.extension_root),
            "skills_dir": str(self.skills_dir),
            "query": query,
            "items": items,
            "raw_output": _raw_output_preview(raw_output),
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
        requested = _install_name_candidates(skill)
        result: SkillHubCommandResult | None = None
        failures: list[str] = []
        installed_name = requested[0]
        for candidate in requested:
            result = _run_command(
                [self.command, "install", candidate, "--dir", str(self.skills_dir)],
                timeout_seconds=timeout_seconds,
            )
            if result.returncode == 0:
                installed_name = candidate
                break
            failures.append(result.combined_output or f"{candidate}: skillhub install failed with exit code {result.returncode}")
        if result is None or result.returncode != 0:
            raise RuntimeError("\n".join(failures) or f"skillhub install failed for {skill}")
        installed = self._resolve_installed_skill(installed_name, before)
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
            "raw_output": _raw_output_preview(raw_output),
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
            parsed.extend(_parse_skill_roots(candidate))
        if len(parsed) == 1:
            return parsed[0][0]
        normalized_requested = _normalize_skill_name(requested)
        for candidate, skill_id in parsed:
            if _normalize_skill_name(skill_id) == normalized_requested or _normalize_skill_name(candidate.name) == normalized_requested:
                return candidate
        if parsed:
            return parsed[0][0]
        for child in sorted(self.skills_dir.iterdir() if self.skills_dir.is_dir() else []):
            if not child.is_dir():
                continue
            for skill_root, skill_id in _parse_skill_roots(child):
                if _normalize_skill_name(skill_id) == normalized_requested or _normalize_skill_name(skill_root.name) == normalized_requested:
                    return skill_root
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


def _search_items(raw_output: str, *, query: str, limit: int) -> list[dict[str, Any]]:
    items = _json_search_items(raw_output)
    if not items:
        items = _text_search_items(raw_output)
    for index, item in enumerate(items):
        item["_score"] = _search_score(item, query=query)
        item["_index"] = index
    items.sort(key=lambda item: (-int(item.get("_score") or 0), int(item.get("_index") or 0), str(item.get("name") or "")))
    projected: list[dict[str, Any]] = []
    for item in items[: max(limit, 0)]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        projected.append(
            {
                "name": name,
                "skill": name,
                "install_name": name,
                "version": str(item.get("version") or "").strip(),
                "summary": _compact_text(str(item.get("summary") or item.get("raw") or ""), limit=700),
                "score": int(item.get("_score") or 0),
            }
        )
    return projected


def _json_search_items(raw_output: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError:
        return []
    candidates = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(candidates, list):
        return []
    items: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        name = _canonical_skill_name(
            str(candidate.get("name") or candidate.get("skill") or candidate.get("id") or candidate.get("slug") or "")
        )
        if not name:
            continue
        items.append(
            {
                "name": name,
                "version": str(candidate.get("version") or ""),
                "summary": str(candidate.get("summary") or candidate.get("description") or ""),
                "raw": json.dumps(candidate, ensure_ascii=False, sort_keys=True, default=str),
            }
        )
    return items


def _text_search_items(raw_output: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in raw_output.splitlines():
        text = raw_line.strip()
        if not text or _is_search_boilerplate(text):
            continue
        if _looks_like_search_header(raw_line):
            if current is not None:
                items.append(_finalize_text_search_item(current))
            current = _parse_search_header(text)
            if current is None:
                continue
            continue
        if current is None:
            name, version, summary = _parse_search_line(text)
            if name:
                items.append({"name": name, "version": version, "summary": summary or text, "raw": text})
            continue
        detail = text.lstrip("-").strip()
        version = _detail_version(detail)
        if version:
            current["version"] = version
            continue
        if detail and not _is_search_boilerplate(detail):
            current.setdefault("descriptions", []).append(detail)
    if current is not None:
        items.append(_finalize_text_search_item(current))
    return [item for item in items if item.get("name")]


def _looks_like_search_header(raw_line: str) -> bool:
    if raw_line[:1].isspace() is False:
        return False
    stripped = raw_line.strip()
    if stripped.startswith("-") or _is_search_boilerplate(stripped):
        return False
    name = _canonical_skill_name(stripped.split()[0] if stripped.split() else "")
    return bool(name)


def _parse_search_header(text: str) -> dict[str, Any] | None:
    cleaned = text.strip()
    parts = re.split(r"\s{2,}", cleaned, maxsplit=1)
    name = _canonical_skill_name(parts[0] if parts else cleaned)
    if not name:
        return None
    title = parts[1].strip() if len(parts) > 1 else cleaned[len(parts[0]) :].strip()
    return {"name": name, "title": _clean_summary_text(title), "version": "", "descriptions": [], "raw": cleaned}


def _finalize_text_search_item(current: dict[str, Any]) -> dict[str, Any]:
    parts = [
        str(current.get("title") or "").strip(),
        *[str(item or "").strip() for item in current.get("descriptions", []) if str(item or "").strip()],
    ]
    summary = "\n".join(_dedupe_texts([part for part in parts if part and part != current.get("name")]))
    return {
        "name": str(current.get("name") or ""),
        "version": str(current.get("version") or ""),
        "summary": summary,
        "raw": str(current.get("raw") or ""),
    }


def _detail_version(text: str) -> str:
    key, sep, value = text.partition(":")
    if not sep:
        key, sep, value = text.partition("：")
    if not sep or key.strip().lower() != "version":
        return ""
    return _version_text(value.strip())


def _clean_summary_text(text: str) -> str:
    key, sep, value = text.partition(":")
    if sep and key.strip().lower() in {"description", "summary"}:
        return value.strip()
    key, sep, value = text.partition("：")
    if sep and key.strip().lower() in {"description", "summary"}:
        return value.strip()
    return text.strip()


def _dedupe_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = " ".join(value.split())
        if not normalized or normalized in seen:
            continue
        result.append(value)
        seen.add(normalized)
    return result


def _parse_search_line(text: str) -> tuple[str, str, str]:
    cleaned = text.strip().lstrip("-*0123456789. \t")
    if not cleaned:
        return "", "", ""
    head, sep, tail = cleaned.partition(":")
    if not sep:
        head, sep, tail = cleaned.partition("：")
    head = head.strip()
    tail = tail.strip()
    tokens = head.split()
    name = _canonical_skill_name(tokens[0] if tokens else head)
    version = ""
    if len(tokens) > 1:
        version = _version_text(tokens[1])
    if not version:
        split_name, split_version = _split_name_version(name)
        name = split_name
        version = split_version
    return name, version, tail


def _install_name_candidates(value: str) -> list[str]:
    raw = str(value or "").strip()
    candidates: list[str] = []
    for candidate in [
        raw,
        raw.partition(":")[0],
        raw.partition("：")[0],
        raw.split()[0] if raw.split() else "",
    ]:
        canonical = _canonical_skill_name(candidate)
        if canonical:
            name, _version = _split_name_version(canonical)
            for item in (canonical, name):
                if item and item not in candidates:
                    candidates.append(item)
    if not candidates:
        raise ValueError("skillhub install requires a valid skill name")
    return candidates


def _canonical_skill_name(value: str) -> str:
    cleaned = str(value or "").strip().lstrip("-*0123456789. \t").strip("`'\"[](){}<>|,;")
    if not cleaned:
        return ""
    cleaned = cleaned.split("/", 1)[0] if cleaned.startswith("/") else cleaned
    cleaned = cleaned.split()[0].strip("：:|,;")
    if not SKILL_NAME_RE.fullmatch(cleaned):
        return ""
    return cleaned


def _split_name_version(value: str) -> tuple[str, str]:
    match = NAME_VERSION_RE.fullmatch(value.strip())
    if not match:
        return value, ""
    name = match.group("name") or value
    version = match.group("version") or ""
    return name, version


def _version_text(value: str) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("v") and re.fullmatch(r"v\d+(?:\.\d+){1,3}(?:[-+.\w]*)?", text, re.IGNORECASE):
        return text[1:]
    if re.fullmatch(r"\d+(?:\.\d+){1,3}(?:[-+.\w]*)?", text):
        return text
    return ""


def _is_search_boilerplate(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    if not normalized:
        return True
    prefixes = (
        "installed skills",
        "available skills",
        "use ",
        "usage:",
        "skillhub ",
        "search results",
        "found ",
        "no skills found",
    )
    return normalized.startswith(prefixes)


def _search_score(item: dict[str, Any], *, query: str) -> int:
    name = _normalized_search_text(str(item.get("name") or ""))
    summary = _normalized_search_text(str(item.get("summary") or item.get("raw") or ""))
    query_text = _normalized_search_text(query)
    terms = [term for term in query_text.split() if term]
    score = 0
    if query_text and name == query_text:
        score += 100
    if query_text and query_text in name:
        score += 80
    if query_text and query_text in summary:
        score += 45
    for term in terms:
        if term in name:
            score += 16
        if term in summary:
            score += 5
    return score


def _normalized_search_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[_./:|]+", " ", text)
    text = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _raw_output_preview(value: str) -> str:
    return _compact_text(value, limit=RAW_OUTPUT_PREVIEW_CHARS)


def _compact_text(value: str, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}\n... [raw output truncated, total {len(text)} chars]"


def _parse_skill_roots(candidate: Path) -> list[tuple[Path, str]]:
    roots = [candidate, *[path.parent for path in candidate.rglob("SKILL.md")]]
    parsed: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            package = parse_skill_directory(root)
        except Exception:
            continue
        parsed.append((root, package.name))
    return parsed


def _normalize_skill_name(value: str) -> str:
    return value.strip().lower().replace("_", "-")
