from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from agent_factory.model_pool.config import resolve_model_root


class ModelStorageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModelDirectoryInfo:
    relative_path: str
    absolute_path: str
    display_name: str
    model_type: str
    architectures: tuple[str, ...]
    tokenizer_available: bool

    def payload(self) -> dict[str, Any]:
        return asdict(self)


class ModelStorage:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = resolve_model_root(root)

    @property
    def modelscope_cache(self) -> Path:
        return self.root / "modelscope"

    def ensure_directories(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.modelscope_cache.mkdir(parents=True, exist_ok=True)

    def list_model_directories(self) -> list[ModelDirectoryInfo]:
        self.ensure_directories()
        models: list[ModelDirectoryInfo] = []
        for config_path in self.root.rglob("config.json"):
            directory = config_path.parent.resolve()
            if not self._contains(directory):
                continue
            models.append(self._describe(directory, config_path=config_path))
        return sorted(models, key=lambda item: item.relative_path.casefold())

    def require_model_directory(self, value: str | Path) -> Path:
        directory = self.resolve_directory(value)
        if not (directory / "config.json").is_file():
            raise ModelStorageError("model directory must contain config.json")
        return directory

    def resolve_directory(self, value: str | Path) -> Path:
        text = str(value or "").strip()
        if not text:
            raise ModelStorageError("model directory is required")
        raw_path = Path(text).expanduser()
        candidate = raw_path if raw_path.is_absolute() else self.root / raw_path
        directory = candidate.resolve()
        if not self._contains(directory):
            raise ModelStorageError(f"model directory must be inside {self.root}")
        if not directory.is_dir():
            raise ModelStorageError(f"model directory does not exist: {directory}")
        return directory

    def _contains(self, path: Path) -> bool:
        return path == self.root or self.root in path.parents

    def _describe(self, directory: Path, *, config_path: Path) -> ModelDirectoryInfo:
        config = _read_config(config_path)
        relative_path = directory.relative_to(self.root).as_posix()
        display_name = _text(config.get("_name_or_path")) or directory.name
        architectures = tuple(
            text for item in _items(config.get("architectures")) if (text := _text(item))
        )
        tokenizer_available = any(
            (directory / filename).is_file()
            for filename in ("tokenizer.json", "tokenizer_config.json", "sentencepiece.bpe.model")
        )
        return ModelDirectoryInfo(
            relative_path=relative_path,
            absolute_path=str(directory),
            display_name=display_name,
            model_type=_text(config.get("model_type")),
            architectures=architectures,
            tokenizer_available=tokenizer_available,
        )


def _read_config(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _items(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str:
    return str(value or "").strip()
