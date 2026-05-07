from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from langchain_core.tools import tool


def _path(value: str) -> Path:
    return Path(value).expanduser()


@tool("search_files", parse_docstring=True)
def search_files(
    root: str,
    pattern: str = "*",
    recursive: bool = True,
    include_dirs: bool = False,
    include_files: bool = True,
    max_results: int = 500,
) -> dict[str, Any]:
    """Find files or directories by glob pattern under an accessible root path.

    Use this when you need to discover candidate files before reading or editing them.

    Args:
        root: Root file or directory path to search under.
        pattern: Glob pattern such as "*.py" or "README*".
        recursive: Search nested directories.
        include_dirs: Include directory matches.
        include_files: Include file matches.
        max_results: Maximum number of results to return.
    """

    base = _path(root)
    iterator = base.rglob(pattern) if recursive else base.glob(pattern)
    results: list[dict[str, str]] = []
    for item in sorted(iterator):
        if item.is_dir() and not include_dirs:
            continue
        if item.is_file() and not include_files:
            continue
        results.append(
            {
                "path": str(item),
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
            }
        )
        if len(results) >= max_results:
            break
    return {
        "root": str(base),
        "pattern": pattern,
        "results": results,
        "truncated": len(results) >= max_results,
    }


@tool("search_text", parse_docstring=True)
def search_text(
    query: str,
    root: str,
    glob: str | None = None,
    case_sensitive: bool = False,
    max_matches: int = 200,
) -> dict[str, Any]:
    """Search text content below an accessible root path.

    Use this to locate definitions, references, errors, configuration keys, or user-specified text.

    Args:
        query: Text or regular expression to search for.
        root: Root file or directory path to search under.
        glob: Optional glob filter such as "*.py" or "*.md".
        case_sensitive: Match case exactly when true.
        max_matches: Maximum number of matches to return.
    """

    base = _path(root)
    rg_path = shutil.which("rg")
    if rg_path:
        command = [rg_path, "--line-number", "--column", "--no-heading"]
        if not case_sensitive:
            command.append("--ignore-case")
        if glob:
            command.extend(["--glob", glob])
        command.extend(["--", query, str(base)])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        matches = _parse_rg_output(completed.stdout, max_matches=max_matches)
        return {
            "root": str(base),
            "query": query,
            "engine": "rg",
            "matches": matches,
            "truncated": len(matches) >= max_matches,
            "exit_code": completed.returncode,
            "stderr": completed.stderr[:4000],
        }

    matches = _python_text_search(
        base,
        query,
        glob=glob,
        case_sensitive=case_sensitive,
        max_matches=max_matches,
    )
    return {
        "root": str(base),
        "query": query,
        "engine": "python",
        "matches": matches,
        "truncated": len(matches) >= max_matches,
    }


@tool("search_inspect_text", parse_docstring=True)
def inspect_text(text: str, max_preview_chars: int = 4000) -> dict[str, Any]:
    """Inspect arbitrary text and summarize its basic structure.

    Use this for quick understanding of pasted text, command output, logs, or generated drafts.

    Args:
        text: Text content to inspect.
        max_preview_chars: Maximum number of preview characters to return.
    """

    lines = text.splitlines()
    words = re.findall(r"\S+", text)
    return {
        "chars": len(text),
        "lines": len(lines),
        "words": len(words),
        "preview": text[:max_preview_chars],
        "truncated": len(text) > max_preview_chars,
    }


@tool("search_inspect_file", parse_docstring=True)
def inspect_file(
    path: str,
    encoding: str = "utf-8",
    max_preview_chars: int = 4000,
) -> dict[str, Any]:
    """Inspect a text file and summarize its basic structure.

    Use this for quick file understanding when full content is unnecessary.

    Args:
        path: Text file path to inspect.
        encoding: Text encoding used to read the file.
        max_preview_chars: Maximum number of preview characters to return.
    """

    target = _path(path)
    content = target.read_text(encoding=encoding)
    lines = content.splitlines()
    words = re.findall(r"\S+", content)
    return {
        "path": str(target),
        "chars": len(content),
        "lines": len(lines),
        "words": len(words),
        "preview": content[:max_preview_chars],
        "truncated": len(content) > max_preview_chars,
    }


def _parse_rg_output(output: str, *, max_matches: int) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for line in output.splitlines():
        path, line_no, column, text = _split_rg_line(line)
        matches.append(
            {
                "path": path,
                "line": line_no,
                "column": column,
                "text": text,
            }
        )
        if len(matches) >= max_matches:
            break
    return matches


def _split_rg_line(line: str) -> tuple[str, int | None, int | None, str]:
    parts = line.split(":", 3)
    if len(parts) != 4:
        return line, None, None, ""
    path, line_no, column, text = parts
    try:
        parsed_line = int(line_no)
    except ValueError:
        parsed_line = None
    try:
        parsed_column = int(column)
    except ValueError:
        parsed_column = None
    return path, parsed_line, parsed_column, text


def _python_text_search(
    base: Path,
    query: str,
    *,
    glob: str | None,
    case_sensitive: bool,
    max_matches: int,
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    needle = query if case_sensitive else query.lower()
    candidates = base.rglob(glob or "*") if base.is_dir() else [base]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            lines = candidate.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for index, text in enumerate(lines, start=1):
            haystack = text if case_sensitive else text.lower()
            if needle in haystack:
                matches.append(
                    {"path": str(candidate), "line": index, "column": None, "text": text}
                )
                if len(matches) >= max_matches:
                    return matches
    return matches


SEARCH_TOOLS = [search_files, search_text, inspect_text, inspect_file]
