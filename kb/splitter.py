"""中文友好切分：优先按段落 / 句号 / 问号断句，而非按空格。"""
from langchain_text_splitters import RecursiveCharacterTextSplitter


def split_text(raw: str, filename: str) -> list[dict]:
    raw = (raw or "").strip()
    if not raw:
        return []
    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""],
        chunk_size=500,
        chunk_overlap=60,
        keep_separator=True,
    )
    pieces = splitter.split_text(raw)
    chunks = []
    for i, p in enumerate(pieces):
        p = p.strip()
        if not p:
            continue
        chunks.append({"id": f"{filename}_{i}", "text": p, "filename": filename})
    return chunks
