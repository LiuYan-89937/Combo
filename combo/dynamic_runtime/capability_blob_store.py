from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import tempfile

from combo.dynamic_runtime.capability_definitions import SkillContentRef, ToolPackageFileRef


class CapabilityBlobStore:
    """Content-addressed immutable storage for capability-owned source material."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    def put_skill_content(
        self,
        *,
        logical_path: str,
        kind: str,
        media_type: str,
        content: bytes,
    ) -> SkillContentRef:
        stored = self._put_content(content)
        return SkillContentRef(
            logical_path=logical_path,
            kind=kind,
            media_type=media_type,
            blob_id=stored[0],
            content_digest=stored[1],
            size_bytes=len(content),
        )

    def put_tool_package_file(
        self,
        *,
        logical_path: str,
        media_type: str,
        content: bytes,
    ) -> ToolPackageFileRef:
        stored = self._put_content(content)
        return ToolPackageFileRef(
            logical_path=logical_path,
            media_type=media_type,
            blob_id=stored[0],
            content_digest=stored[1],
            size_bytes=len(content),
        )

    def _put_content(self, content: bytes) -> tuple[str, str]:
        digest = sha256(content).hexdigest()
        blob_id = f"sha256:{digest}"
        target = self._blob_path(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            self._verify_blob(target, expected_digest=digest, expected_size=len(content))
        else:
            descriptor, temporary_name = tempfile.mkstemp(prefix="blob-", dir=target.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                if target.exists():
                    self._verify_blob(target, expected_digest=digest, expected_size=len(content))
                else:
                    os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return blob_id, digest

    def read(self, reference: SkillContentRef | ToolPackageFileRef) -> bytes:
        algorithm, separator, digest = reference.blob_id.partition(":")
        if algorithm != "sha256" or not separator or digest != reference.content_digest:
            raise ValueError("capability content reference has an unsupported blob identity")
        target = self._blob_path(digest)
        if not target.is_file():
            raise LookupError(f"capability blob is unavailable: {reference.blob_id}")
        content = target.read_bytes()
        self._verify_content(
            content,
            expected_digest=reference.content_digest,
            expected_size=reference.size_bytes,
        )
        return content

    def read_text(self, reference: SkillContentRef | ToolPackageFileRef) -> str:
        if not reference.media_type.startswith("text/") and reference.media_type not in {
            "application/json",
            "application/yaml",
        }:
            raise TypeError(f"capability content is not textual: {reference.media_type}")
        try:
            return self.read(reference).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("capability text content is not valid UTF-8") from exc

    def _blob_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("capability blob digest must be lowercase SHA-256")
        return self._root / "sha256" / digest[:2] / digest

    @staticmethod
    def _verify_blob(path: Path, *, expected_digest: str, expected_size: int) -> None:
        CapabilityBlobStore._verify_content(
            path.read_bytes(),
            expected_digest=expected_digest,
            expected_size=expected_size,
        )

    @staticmethod
    def _verify_content(content: bytes, *, expected_digest: str, expected_size: int) -> None:
        if len(content) != expected_size or sha256(content).hexdigest() != expected_digest:
            raise RuntimeError("capability blob content differs from its immutable identity")
