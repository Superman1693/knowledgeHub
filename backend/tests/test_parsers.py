"""解析器测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import ParseError
from app.services import parsers


def test_parse_markdown_extracts_headings(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("# 一级标题\n\n正文内容\n\n## 二级标题\n\n更多内容", encoding="utf-8")
    doc = parsers.parse(path, "md")
    assert "正文内容" in doc.text
    assert "一级标题" in doc.headings
    assert "二级标题" in doc.headings


def test_parse_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("纯文本内容", encoding="utf-8")
    doc = parsers.parse(path, "txt")
    assert doc.text == "纯文本内容"


def test_parse_unsupported_raises(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"\x00\x01\x02")
    with pytest.raises(ParseError):
        parsers.parse(path, "bin")


def test_parse_docx(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("文档标题", level=1)
    document.add_paragraph("这是正文段落。")
    path = tmp_path / "a.docx"
    document.save(str(path))
    parsed = parsers.parse(path, "docx")
    assert "这是正文段落" in parsed.text
    assert "文档标题" in parsed.headings
