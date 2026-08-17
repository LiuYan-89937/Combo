#!/usr/bin/env python3
"""Precompile bundled Python resources for deterministic desktop startup."""

from __future__ import annotations

import argparse
import compileall
import py_compile
from pathlib import Path


def _compile(root: Path) -> bool:
    return compileall.compile_dir(
        root,
        quiet=1,
        force=True,
        optimize=0,
        invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", default=[], type=Path)
    args = parser.parse_args()

    roots = [path.resolve() for path in args.source]
    if not roots:
        parser.error("at least one compilation root is required")

    failed = [root for root in roots if not root.is_dir() or not _compile(root)]
    if failed:
        for root in failed:
            print(f"Python resource precompilation failed: {root}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
