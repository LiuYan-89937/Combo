from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from langchain_core.tools import tool


def _path(value: str) -> Path:
    return Path(value).expanduser()


@tool("file_read", parse_docstring=True)
def read_file(path: str, encoding: str = "utf-8", max_chars: int = 20000) -> dict[str, Any]:
    """Read a text file from an accessible filesystem path.

    Use this when you need to inspect file contents before deciding what to build,
    modify, or explain.

    Args:
        path: Absolute or relative path to the text file.
        encoding: Text encoding used to read the file.
        max_chars: Maximum number of characters to return.
    """

    target = _path(path)
    content = target.read_text(encoding=encoding)
    truncated = len(content) > max_chars
    return {
        "path": str(target),
        "exists": target.exists(),
        "type": "file" if target.is_file() else "other",
        "content": content[:max_chars],
        "truncated": truncated,
        "chars": len(content),
    }


@tool("file_write", parse_docstring=True)
def write_file(
    path: str,
    content: str,
    encoding: str = "utf-8",
    create_parents: bool = True,
) -> dict[str, Any]:
    """Write text content to an accessible filesystem path.

    Use this for creating generated specs, source files, notes, or other text artifacts.

    Args:
        path: Destination file path.
        content: Full text content to write.
        encoding: Text encoding used to write the file.
        create_parents: Create missing parent directories before writing.
    """

    target = _path(path)
    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding=encoding)
    return {"path": str(target), "status": "written", "bytes": len(content.encode(encoding))}


@tool("file_patch", parse_docstring=True)
def patch_file(
    path: str,
    old: str,
    new: str,
    encoding: str = "utf-8",
    count: int = 1,
) -> dict[str, Any]:
    """Replace text in a file for a small targeted edit.

    Use this only when you know the exact text to replace.

    Args:
        path: File path to edit.
        old: Exact text to search for.
        new: Replacement text.
        encoding: Text encoding used to read and write the file.
        count: Maximum number of replacements to perform.
    """

    target = _path(path)
    content = target.read_text(encoding=encoding)
    occurrences = content.count(old)
    if occurrences == 0:
        return {"path": str(target), "status": "unchanged", "replacements": 0}
    patched = content.replace(old, new, count)
    target.write_text(patched, encoding=encoding)
    return {
        "path": str(target),
        "status": "patched",
        "replacements": min(occurrences, count),
        "occurrences": occurrences,
    }


@tool("file_list", parse_docstring=True)
def list_path(
    path: str,
    recursive: bool = False,
    include_dirs: bool = True,
    include_files: bool = True,
    max_entries: int = 500,
) -> dict[str, Any]:
    """List files and directories under an accessible filesystem path.

    Use this to inspect a folder structure before reading or editing files.

    Args:
        path: Directory path to list.
        recursive: Include nested files and directories.
        include_dirs: Include directories in the results.
        include_files: Include files in the results.
        max_entries: Maximum number of entries to return.
    """

    root = _path(path)
    iterator = root.rglob("*") if recursive else root.iterdir()
    entries: list[dict[str, Any]] = []
    for item in sorted(iterator):
        if item.is_dir() and not include_dirs:
            continue
        if item.is_file() and not include_files:
            continue
        entries.append(
            {
                "path": str(item),
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
            }
        )
        if len(entries) >= max_entries:
            break
    return {
        "path": str(root),
        "exists": root.exists(),
        "entries": entries,
        "truncated": len(entries) >= max_entries,
    }


@tool("file_exists", parse_docstring=True)
def path_exists(path: str) -> dict[str, Any]:
    """Check whether a file or directory exists.

    Use this before reading, writing, copying, or creating paths when existence matters.

    Args:
        path: File or directory path to check.
    """

    target = _path(path)
    kind = "missing"
    if target.is_file():
        kind = "file"
    elif target.is_dir():
        kind = "directory"
    return {"path": str(target), "exists": target.exists(), "type": kind}


@tool("file_mkdir", parse_docstring=True)
def make_directory(path: str, parents: bool = True, exist_ok: bool = True) -> dict[str, Any]:
    """Create a directory at an accessible filesystem path.

    Use this when a generated package or artifact needs a directory before writing files.

    Args:
        path: Directory path to create.
        parents: Create missing parent directories.
        exist_ok: Do not fail if the directory already exists.
    """

    target = _path(path)
    target.mkdir(parents=parents, exist_ok=exist_ok)
    return {"path": str(target), "status": "created"}


@tool("file_copy", parse_docstring=True)
def copy_path(source: str, destination: str, overwrite_directory: bool = True) -> dict[str, Any]:
    """Copy a file or directory to another accessible filesystem path.

    Use this when preserving or reusing an existing artifact is better than rewriting it.

    Args:
        source: Source file or directory path.
        destination: Destination file or directory path.
        overwrite_directory: Allow merging into an existing destination directory.
    """

    src = _path(source)
    dst = _path(destination)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=overwrite_directory)
    else:
        shutil.copy2(src, dst)
    return {"source": str(src), "destination": str(dst), "status": "copied"}


FILE_TOOLS = [
    read_file,
    write_file,
    patch_file,
    list_path,
    path_exists,
    make_directory,
    copy_path,
]
