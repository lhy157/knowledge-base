"""向量存储门面：按 settings.vector_backend 在 Chroma / 腾讯云向量库之间切换。

公共接口（与具体后端无关），供 rag.py / routers/document.py 调用：
    add_chunks(library_id, chunks)
    query(library_id, text, top_k)            -> [{text, filename, snippet}]
    delete_document(library_id, doc_id)
    count_chunks(library_id)                  -> int
    get_library_stats(library_id)             -> {chunk_count, document_count}
    get_document_chunks(library_id, doc_id)   -> [{id, text, snippet, filename}]
    collection_name(library_id)               -> str

切换方式：在 .env 设置 VECTOR_BACKEND=chroma（默认）或 tencent。
"""
from typing import List, Dict, Any

from kb.config import settings


_backend = None


def _get_backend():
    """懒加载并缓存当前选中的向量后端模块。"""
    global _backend
    if _backend is None:
        if settings.vector_backend == "tencent":
            from kb import vectorstore_tencent as mod
        else:
            from kb import vectorstore_chroma as mod
        _backend = mod
    return _backend


def add_chunks(library_id: int, chunks: List[Dict[str, Any]]):
    return _get_backend().add_chunks(library_id, chunks)


def query(library_id: int, text: str, top_k: int) -> List[Dict[str, Any]]:
    return _get_backend().query(library_id, text, top_k)


def delete_document(library_id: int, doc_id: str):
    return _get_backend().delete_document(library_id, doc_id)


def count_chunks(library_id: int) -> int:
    return _get_backend().count_chunks(library_id)


def get_library_stats(library_id: int) -> Dict[str, Any]:
    return _get_backend().get_library_stats(library_id)


def get_document_chunks(library_id: int, doc_id: str) -> List[Dict[str, Any]]:
    return _get_backend().get_document_chunks(library_id, doc_id)


def collection_name(library_id: int) -> str:
    return _get_backend().collection_name(library_id)
