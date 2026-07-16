"""文档解析：支持 PDF / Word / Excel / Markdown / TXT，返回切分后的片段。"""
import io
from typing import List, Dict, Any

from kb.splitter import split_text


def load_file(filename: str, data: bytes) -> List[Dict[str, Any]]:
    name = (filename or "").lower()
    # 无扩展名时按文件头魔数推断，避免图片等二进制被当纯文本处理
    if not name or "." not in name:
        if data.startswith(b"%PDF"):
            name = "unknown.pdf"
        elif data.startswith(b"PK\x03\x04"):
            name = "unknown.docx"
        else:
            # 无扩展名且无法识别为已知文档格式 -> 直接拒绝，
            # 避免二进制（图片/压缩包/可执行文件）被当文本污染检索
            raise ValueError(
                "无法识别的文件类型，仅支持 PDF / Word / Excel / Markdown / TXT"
            )
    try:
        if name.endswith(".pdf"):
            raw = _pdf(data)
        elif name.endswith(".docx"):
            raw = _docx(data)
        elif name.endswith((".xlsx", ".xls")):
            raw = _xlsx(data)
        elif name.endswith((".md", ".markdown", ".txt", ".text")):
            # 文本类：若含 NUL 字节视为二进制（如伪装成 .txt 的 docx/zip），拒绝
            if b"\x00" in data:
                raise ValueError(
                    "文件疑似二进制内容，仅支持纯文本 / Markdown"
                )
            raw = data.decode("utf-8", errors="ignore")
        else:
            # 兜底：未知扩展名（.zip/.exe/.png 等）直接拒绝，
            # 不再静默当纯文本处理（会污染向量检索）
            raise ValueError(
                f"不支持的文件类型：{filename}，仅支持 PDF / Word / Excel / Markdown / TXT"
            )
    except ValueError:
        # 业务可识别的错误（类型不支持）原样抛出，由路由层转 400
        raise
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

