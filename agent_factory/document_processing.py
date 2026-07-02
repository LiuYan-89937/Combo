from __future__ import annotations

from dataclasses import dataclass
import html
import importlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


TEXT_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".csv",
    ".tsv",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".sql",
    ".html",
    ".htm",
    ".xml",
    ".log",
}
PDF_EXTENSIONS = {".pdf"}
DOCX_EXTENSIONS = {".docx"}
OFFICE_EXTENSIONS = {
    ".doc",
    *DOCX_EXTENSIONS,
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".rtf",
    ".odt",
    ".ods",
    ".odp",
    ".epub",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".heic"}
EMAIL_EXTENSIONS = {".eml", ".msg"}
SUPPORTED_FILE_EXTENSIONS = (
    TEXT_EXTENSIONS
    | PDF_EXTENSIONS
    | OFFICE_EXTENSIONS
    | IMAGE_EXTENSIONS
    | EMAIL_EXTENSIONS
)


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    title: str
    uri: str
    document_type: str
    content: str
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ParseResult:
    documents: list[ParsedDocument]
    warnings: list[str]


def parse_file(path: Path, *, root: Path | None = None, metadata: dict[str, Any] | None = None) -> ParseResult:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_FILE_EXTENSIONS:
        return ParseResult(documents=[], warnings=[f"unsupported file type: {suffix or 'no_extension'}"])
    resolved_root = root or path.parent
    base_metadata = dict(metadata or {})
    warnings: list[str] = []
    for parser in (
        _parse_with_docling,
        _parse_with_unstructured,
        _parse_with_markitdown,
        _parse_with_langchain,
        _parse_with_text_fallback,
    ):
        result = parser(path=path, suffix=suffix, root=resolved_root, metadata=base_metadata)
        if result.documents:
            return result
        warnings.extend(result.warnings)
    return ParseResult(documents=[], warnings=_dedupe_warnings(warnings))


def parse_url(url: str, *, metadata: dict[str, Any] | None = None) -> ParseResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ParseResult(documents=[], warnings=["url_requires_http_or_https"])
    try:
        httpx = importlib.import_module("httpx")
        response = httpx.get(url, timeout=20.0, follow_redirects=True)
        response.raise_for_status()
    except Exception as exc:
        return ParseResult(documents=[], warnings=[f"url_fetch_failed: {type(exc).__name__}: {exc}"])
    content_type = response.headers.get("content-type", "")
    if "html" in content_type.lower():
        text = html_to_text(response.text)
    else:
        text = response.text.strip()
    title = parsed.netloc + parsed.path
    document = ParsedDocument(
        title=str((metadata or {}).get("title") or title or url),
        uri=url,
        document_type="web_snapshot",
        content=text,
        metadata={
            **dict(metadata or {}),
            "url": url,
            "status_code": response.status_code,
            "content_type": content_type,
            "loader": "httpx",
        },
    )
    return ParseResult(documents=[document] if text else [], warnings=[] if text else ["url_returned_empty_content"])


def html_to_text(value: str) -> str:
    BeautifulSoup = importlib.import_module("bs4").BeautifulSoup
    soup = BeautifulSoup(value, "html.parser")
    for item in soup(["script", "style", "noscript"]):
        item.decompose()
    text = soup.get_text("\n")
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.strip() for line in text.splitlines())).strip()


def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="ignore")


def _parse_with_docling(
    *,
    path: Path,
    suffix: str,
    root: Path,
    metadata: dict[str, Any],
) -> ParseResult:
    if suffix in TEXT_EXTENSIONS and suffix not in {".html", ".htm", ".md", ".markdown", ".csv"}:
        return ParseResult(documents=[], warnings=[])
    try:
        converter_cls = importlib.import_module("docling.document_converter").DocumentConverter
    except ModuleNotFoundError:
        return ParseResult(documents=[], warnings=["docling_not_installed"])
    try:
        result = converter_cls().convert(str(path))
        document = result.document
        if hasattr(document, "export_to_markdown"):
            content = str(document.export_to_markdown()).strip()
        elif hasattr(document, "export_to_text"):
            content = str(document.export_to_text()).strip()
        else:
            content = str(document).strip()
    except Exception as exc:
        return ParseResult(documents=[], warnings=[f"docling_failed: {type(exc).__name__}: {exc}"])
    return _single_document_result(
        path=path,
        root=root,
        suffix=suffix,
        content=content,
        loader="docling",
        metadata=metadata,
    )


def _parse_with_unstructured(
    *,
    path: Path,
    suffix: str,
    root: Path,
    metadata: dict[str, Any],
) -> ParseResult:
    if suffix in TEXT_EXTENSIONS and suffix not in {".html", ".htm"}:
        return ParseResult(documents=[], warnings=[])
    try:
        partition = importlib.import_module("unstructured.partition.auto").partition
    except ModuleNotFoundError:
        return ParseResult(documents=[], warnings=["unstructured_not_installed"])
    try:
        elements = partition(filename=str(path))
        content = "\n\n".join(str(item).strip() for item in elements if str(item).strip()).strip()
    except Exception as exc:
        return ParseResult(documents=[], warnings=[f"unstructured_failed: {type(exc).__name__}: {exc}"])
    return _single_document_result(
        path=path,
        root=root,
        suffix=suffix,
        content=content,
        loader="unstructured",
        metadata=metadata,
    )


def _parse_with_markitdown(
    *,
    path: Path,
    suffix: str,
    root: Path,
    metadata: dict[str, Any],
) -> ParseResult:
    if suffix in TEXT_EXTENSIONS and suffix not in {".html", ".htm"}:
        return ParseResult(documents=[], warnings=[])
    try:
        markitdown_cls = importlib.import_module("markitdown").MarkItDown
    except ModuleNotFoundError:
        return ParseResult(documents=[], warnings=["markitdown_not_installed"])
    try:
        result = markitdown_cls().convert(str(path))
        content = str(getattr(result, "text_content", "") or "").strip()
    except Exception as exc:
        return ParseResult(documents=[], warnings=[f"markitdown_failed: {type(exc).__name__}: {exc}"])
    return _single_document_result(
        path=path,
        root=root,
        suffix=suffix,
        content=content,
        loader="markitdown",
        metadata=metadata,
    )


def _parse_with_langchain(
    *,
    path: Path,
    suffix: str,
    root: Path,
    metadata: dict[str, Any],
) -> ParseResult:
    loader = _build_langchain_loader(path=path, suffix=suffix)
    if loader is None:
        return ParseResult(documents=[], warnings=[])
    try:
        documents = loader.load()
    except (ImportError, ModuleNotFoundError) as exc:
        return ParseResult(documents=[], warnings=[f"langchain_loader_dependency_missing: {type(exc).__name__}: {exc}"])
    except Exception as exc:
        return ParseResult(documents=[], warnings=[f"langchain_loader_failed: {type(exc).__name__}: {exc}"])
    content = "\n\n".join(document.page_content for document in documents).strip()
    loader_name = _loader_name(documents)
    return _single_document_result(
        path=path,
        root=root,
        suffix=suffix,
        content=content,
        loader=loader_name,
        metadata=metadata,
    )


def _parse_with_text_fallback(
    *,
    path: Path,
    suffix: str,
    root: Path,
    metadata: dict[str, Any],
) -> ParseResult:
    if suffix not in TEXT_EXTENSIONS:
        return ParseResult(documents=[], warnings=[])
    try:
        content = read_text_file(path)
        if suffix in {".html", ".htm"}:
            content = html_to_text(content)
    except Exception as exc:
        return ParseResult(documents=[], warnings=[f"text_loader_failed: {type(exc).__name__}: {exc}"])
    return _single_document_result(
        path=path,
        root=root,
        suffix=suffix,
        content=content,
        loader="internal_text",
        metadata=metadata,
    )


def _build_langchain_loader(*, path: Path, suffix: str):
    try:
        document_loaders = importlib.import_module("langchain_community.document_loaders")
    except ModuleNotFoundError:
        return None
    if suffix in PDF_EXTENSIONS:
        return document_loaders.PyPDFLoader(str(path))
    if suffix == ".docx":
        return document_loaders.Docx2txtLoader(str(path))
    if suffix in {".html", ".htm"}:
        return document_loaders.BSHTMLLoader(str(path), open_encoding="utf-8")
    if suffix in TEXT_EXTENSIONS:
        return document_loaders.TextLoader(str(path), encoding="utf-8", autodetect_encoding=True)
    return None


def _single_document_result(
    *,
    path: Path,
    root: Path,
    suffix: str,
    content: str,
    loader: str,
    metadata: dict[str, Any],
) -> ParseResult:
    text = content.strip()
    if not text:
        return ParseResult(documents=[], warnings=[f"{loader}_returned_empty_content"])
    try:
        relative = str(path.relative_to(root))
    except ValueError:
        relative = path.name
    document_type = suffix.removeprefix(".") or "file"
    return ParseResult(
        documents=[
            ParsedDocument(
                title=relative,
                uri=str(path),
                document_type=document_type,
                content=text,
                metadata={
                    **metadata,
                    "file_name": path.name,
                    "relative_path": relative,
                    "file_type": document_type,
                    "loader": loader,
                },
            )
        ],
        warnings=[],
    )


def _loader_name(documents: list[Any]) -> str:
    if not documents:
        return "none"
    loaders = [str(document.metadata.get("loader") or "").strip() for document in documents if getattr(document, "metadata", None)]
    if loaders and loaders[0]:
        return loaders[0]
    return "langchain_document_loader"


def _dedupe_warnings(warnings: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        if warning and warning not in seen:
            result.append(warning)
            seen.add(warning)
    return result
