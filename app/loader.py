"""文档解析：支持 PDF / Word / Excel / Markdown / TXT，返回切分后的片段。"""
import io
from typing import List

from app.splitter import split_text


def load_file(filename: str, data: bytes) -> List[dict]:
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            raw = _pdf(data)
        elif name.endswith(".docx"):
            raw = _docx(data)
        elif name.endswith((".xlsx", ".xls")):
            raw = _xlsx(data)
        elif name.endswith((".md", ".markdown", ".txt", ".text")):
            raw = data.decode("utf-8", errors="ignore")
        else:
            # 兜底按纯文本处理
            raw = data.decode("utf-8", errors="ignore")
    except Exception as e:
        raise RuntimeError(f"解析文档失败（{filename}）：{e}")
    return split_text(raw, filename)


def _pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages)


def _docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def _xlsx(data: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                lines.append(" | ".join(cells))
    return "\n".join(lines)
