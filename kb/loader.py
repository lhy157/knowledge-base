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

    try:
        doc = Document(io.BytesIO(data))
        return "\n".join(p.text for p in doc.paragraphs if p.text)
    except Exception as e:
        # python-docx 已知 bug：某些含复杂元素（文本框/SmartArt/OLE）的 .docx
        # 内部关系目标为 "NULL" 字符串，导致报
        #   "There is no item named 'NULL' in the archive"
        # fallback：直接从 ZIP 内 word/document.xml 用 lxml 提取纯文本。
        return _docx_fallback(data, e)


def _docx_fallback(data: bytes, original_error: Exception) -> str:
    """python-docx 解析失败时的 fallback：直接从 ZIP 内 word/document.xml 提取文本。

    适用场景：
    - 文档含 SmartArt / 文本框 / OLE 嵌入等复杂元素，内部 relTarget 为 "NULL"
    - WPS / 第三方工具生成的非标准 docx
    """
    import zipfile
    import xml.etree.ElementTree as ET

    # docx 本质是 ZIP 包，word/document.xml 是正文 XML
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml_bytes = zf.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as ze:
        raise RuntimeError(f"docx ZIP 结构异常（非标准 .docx）：{ze}") from original_error

    # 命名空间处理：Word XML 使用 w: 前缀
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = ET.fromstring(xml_bytes)
    paragraphs = root.findall(".//w:p", ns)

    texts = []
    for p in paragraphs:
        runs = p.findall(".//w:t", ns)
        para_text = "".join(r.text or "" for r in runs if r.text)
        if para_text.strip():
            texts.append(para_text.strip())

    if not texts:
        raise RuntimeError(f"docx fallback 提取到空文本，原始错误：{original_error}") from original_error

    return "\n".join(texts)


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

