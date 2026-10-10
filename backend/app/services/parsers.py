"""文档解析器：按扩展名分派，输出纯文本（尽量保留结构与页码）。

设计目标：可扩展。新增格式只需注册一个解析函数。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.exceptions import ParseError
from app.storage import files

# 纯文本类扩展名：直接按文本读取
TEXT_EXTENSIONS = {
    "md", "markdown", "txt", "py", "js", "ts", "jsx", "tsx",
    "html", "htm", "css", "json", "yaml", "yml", "ini", "toml",
    "conf", "cfg", "env", "java", "go", "rs", "c", "cpp", "h", "hpp",
    "cs", "php", "rb", "sql", "sh", "bat", "xml", "csv", "log",
}


@dataclass
class ParsedDocument:
    """解析结果。"""

    text: str
    # 逐页文本（仅 PDF 等分页格式提供），用于保留页码
    pages: list[str] = field(default_factory=list)
    # 结构提示：如从 Markdown 提取的标题行
    headings: list[str] = field(default_factory=list)


def _parse_text(path: Path) -> ParsedDocument:
    text = path.read_text(encoding="utf-8", errors="replace")
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            headings.append(stripped.lstrip("#").strip())
    return ParsedDocument(text=text, headings=headings)


def _parse_pdf(path: Path) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise ParseError("缺少 PDF 解析依赖 pypdf，请先安装依赖") from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"PDF 打开失败：{exc}") from exc

    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - 单页失败不影响整体
            pages.append("")
    text = "\n\n".join(pages).strip()
    if not text:
        raise ParseError("PDF 未提取到文本内容（可能是扫描件，需 OCR）")
    return ParsedDocument(text=text, pages=pages)


def _parse_docx(path: Path) -> ParsedDocument:
    try:
        import docx  # python-docx
    except ImportError as exc:  # pragma: no cover
        raise ParseError("缺少 DOCX 解析依赖 python-docx，请先安装依赖") from exc

    try:
        document = docx.Document(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"DOCX 打开失败：{exc}") from exc

    lines: list[str] = []
    headings: list[str] = []
    for para in document.paragraphs:
        txt = para.text.strip()
        if not txt:
            continue
        style = (para.style.name or "").lower() if para.style else ""
        if style.startswith("heading") or style.startswith("标题"):
            # 保留标题结构，用 Markdown 标题标记
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            lines.append(f"{'#' * min(int(level), 6)} {txt}")
            headings.append(txt)
        else:
            lines.append(txt)

    # 表格内容以管道分隔追加，避免丢失
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))

    text = "\n".join(lines).strip()
    if not text:
        raise ParseError("DOCX 未提取到文本内容")
    return ParsedDocument(text=text, headings=headings)


def parse(path: Path, ext: str) -> ParsedDocument:
    """按扩展名解析文档。"""
    ext = ext.lower().lstrip(".")
    if ext == "pdf":
        return _parse_pdf(path)
    if ext == "docx":
        return _parse_docx(path)
    if ext in TEXT_EXTENSIONS:
        return _parse_text(path)
    raise ParseError(f"暂不支持解析的格式：.{ext}")
