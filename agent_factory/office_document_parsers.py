from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class OfficeDocumentContent:
    content: str
    loader: str


def parse_office_document(path: Path, suffix: str) -> OfficeDocumentContent | None:
    parser = _PARSERS.get(suffix)
    if parser is None:
        return None
    return parser(path)


def _parse_docx(path: Path) -> OfficeDocumentContent:
    mammoth = importlib.import_module("mammoth")
    markdownify = importlib.import_module("markdownify").markdownify
    with path.open("rb") as source:
        html = mammoth.convert_to_html(source).value
    return OfficeDocumentContent(content=markdownify(html).strip(), loader="mammoth")


def _parse_pptx(path: Path) -> OfficeDocumentContent:
    pptx = importlib.import_module("pptx")
    presentation = pptx.Presentation(str(path))
    sections: list[str] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        slide_lines = [f"## Slide {slide_number}"]
        shapes = sorted(slide.shapes, key=lambda shape: (shape.top or 0, shape.left or 0))
        for shape in shapes:
            if getattr(shape, "has_table", False):
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
                table = _markdown_table(rows)
                if table:
                    slide_lines.append(table)
            elif getattr(shape, "has_chart", False):
                chart = _pptx_chart(shape.chart)
                if chart:
                    slide_lines.append(chart)
            elif (description := _pptx_picture_description(shape)):
                slide_lines.append(f"[Image: {description}]")
            elif getattr(shape, "has_text_frame", False):
                text = str(shape.text or "").strip()
                if text:
                    slide_lines.append(text)
        notes_slide = getattr(slide, "notes_slide", None) if slide.has_notes_slide else None
        notes_frame = getattr(notes_slide, "notes_text_frame", None)
        notes = str(getattr(notes_frame, "text", "") or "").strip()
        if notes:
            slide_lines.extend(("### Notes", notes))
        sections.append("\n\n".join(slide_lines))
    return OfficeDocumentContent(content="\n\n".join(sections).strip(), loader="python-pptx")


def _parse_xlsx(path: Path) -> OfficeDocumentContent:
    openpyxl = importlib.import_module("openpyxl")
    workbook = openpyxl.load_workbook(filename=str(path), read_only=True, data_only=True)
    try:
        sections = [
            _spreadsheet_section(sheet.title, sheet.iter_rows(values_only=True))
            for sheet in workbook.worksheets
        ]
    finally:
        workbook.close()
    return OfficeDocumentContent(content="\n\n".join(filter(None, sections)), loader="openpyxl")


def _parse_xls(path: Path) -> OfficeDocumentContent:
    xlrd = importlib.import_module("xlrd")
    workbook = xlrd.open_workbook(str(path), on_demand=True)
    try:
        sections = [
            _spreadsheet_section(
                sheet.name,
                (sheet.row_values(row_index) for row_index in range(sheet.nrows)),
            )
            for sheet in workbook.sheets()
        ]
    finally:
        workbook.release_resources()
    return OfficeDocumentContent(content="\n\n".join(filter(None, sections)), loader="xlrd")


def _parse_msg(path: Path) -> OfficeDocumentContent:
    olefile = importlib.import_module("olefile")
    message = olefile.OleFileIO(str(path))
    try:
        headers = {
            "From": _ole_text(message, "__substg1.0_0C1F001F"),
            "To": _ole_text(message, "__substg1.0_0E04001F"),
            "Subject": _ole_text(message, "__substg1.0_0037001F"),
        }
        body = _ole_text(message, "__substg1.0_1000001F")
    finally:
        message.close()
    lines = ["# Email Message"]
    lines.extend(f"**{name}:** {value}" for name, value in headers.items() if value)
    if body:
        lines.extend(("## Content", body))
    return OfficeDocumentContent(content="\n\n".join(lines).strip(), loader="olefile")


def _ole_text(message: Any, stream_path: str) -> str:
    if not message.exists(stream_path):
        return ""
    data = message.openstream(stream_path).read()
    for encoding in ("utf-16-le", "utf-8"):
        try:
            return data.decode(encoding).rstrip("\x00").strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore").rstrip("\x00").strip()


def _pptx_picture_description(shape: Any) -> str:
    try:
        shape_type = importlib.import_module("pptx.enum.shapes").MSO_SHAPE_TYPE
        if shape.shape_type not in {shape_type.PICTURE, shape_type.PLACEHOLDER}:
            return ""
        properties = shape._element._nvXxPr.cNvPr
        return str(properties.attrib.get("descr") or properties.attrib.get("title") or shape.name).strip()
    except (AttributeError, TypeError):
        return ""


def _pptx_chart(chart: Any) -> str:
    title = "Chart"
    if getattr(chart, "has_title", False):
        title = str(chart.chart_title.text_frame.text or title).strip()
    lines = [f"### {title}"]
    try:
        categories = [str(value) for value in chart.plots[0].categories]
    except (AttributeError, IndexError, TypeError):
        categories = []
    if categories:
        lines.append("Categories: " + ", ".join(categories))
    for series in chart.series:
        name = str(getattr(series, "name", "") or "Series").strip()
        values = ", ".join(str(value) for value in getattr(series, "values", ()))
        lines.append(f"- {name}: {values}" if values else f"- {name}")
    return "\n".join(lines) if len(lines) > 1 else ""


def _spreadsheet_section(title: str, rows: Any) -> str:
    normalized = [_trim_row(row) for row in rows]
    while normalized and not normalized[-1]:
        normalized.pop()
    table = _markdown_table(normalized)
    return f"## {title}\n\n{table}" if table else ""


def _trim_row(row: Any) -> list[Any]:
    values = list(row)
    while values and values[-1] in (None, ""):
        values.pop()
    return values


def _markdown_table(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    if width == 0:
        return ""
    padded = [row + [None] * (width - len(row)) for row in rows]
    header = [str(value) if value not in (None, "") else f"Column {index + 1}" for index, value in enumerate(padded[0])]
    lines = [
        "| " + " | ".join(_markdown_cell(value) for value in header) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    lines.extend("| " + " | ".join(_markdown_cell(value) for value in row) + " |" for row in padded[1:])
    return "\n".join(lines)


def _markdown_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", "<br>").strip()


_PARSERS: dict[str, Callable[[Path], OfficeDocumentContent]] = {
    ".docx": _parse_docx,
    ".pptx": _parse_pptx,
    ".xlsx": _parse_xlsx,
    ".xls": _parse_xls,
    ".msg": _parse_msg,
}
