"""Chroma 向量库封装：按 library_id 建独立 collection，实现多租户隔离。"""
from typing import List, Dict, Any
import os

import chromadb

from kb.config import settings
from kb.llm import embed


_client = None


def get_client():
    global _client
    if _client is None:
        os.makedirs(settings.chroma_dir, exist_ok=True)
        _client = chromadb.PersistentClient(path=settings.chroma_dir)
    return _client


def collection_name(library_id: int) -> str:
    return f"kb_{library_id}"


def get_collection(library_id: int):
    # 不在 collection 上挂 embedding_function：Chroma 1.x 默认会尝试加载 all-MiniLM 并联网下载(79MB)，
    # 改为在 add/query 时显式传入通义 text-embedding-v3 向量，避免下载且保证维度一致(1024)。
    return get_client().get_or_create_collection(
        name=collection_name(library_id),
        metadata={"hnsw:space": "cosine"},
    )


def add_chunks(library_id: int, chunks: List[Dict[str, Any]]):
    if not chunks:
        return
    col = get_collection(library_id)
    texts = [c["text"] for c in chunks]
    # 显式走通义 text-embedding-v3，维度由 .env EMBEDDING_DIM 控制（默认 1024）
    # 不再使用 Chroma 默认 embedding_function，避免联网下载 all-MiniLM 模型导致超时。
    embeddings = embed(texts)
    col.add(
        ids=[c["id"] for c in chunks],
        embeddings=embeddings,
        documents=texts,
        metadatas=[
            {
                "doc_id": c["doc_id"],
                "filename": c["filename"],
                "snippet": c["text"][:200],
            }
            for c in chunks
        ],
    )


def query(library_id: int, vector: List[float], top_k: int) -> List[Dict[str, Any]]:
    col = get_collection(library_id)
    res = col.query(query_embeddings=[vector], n_results=top_k)
    docs = res.get("documents") or [[]]
    metas = res.get("metadatas") or [[]]
    out = []
    for d, m in zip(docs[0], metas[0]):
        m = m or {}
        out.append(
            {
                "text": d,
                "filename": m.get("filename", ""),
                "snippet": m.get("snippet", ""),
            }
        )
    return out


def delete_document(library_id: int, doc_id: str):
    col = get_collection(library_id)
    col.delete(where={"doc_id": doc_id})


def count_chunks(library_id: int) -> int:
    try:
        return get_collection(library_id).count()
    except Exception:
        return 0


def get_library_stats(library_id: int) -> Dict[str, Any]:
    """返回知识库统计：向量总条数、按 doc_id 聚合的文档数。"""
    col = get_collection(library_id)
    try:
        total = col.count()
    except Exception:
        total = 0
    # 通过 metadatas 聚合 doc_id 数量；无数据时返回 0
    doc_ids = set()
    try:
        all_meta = col.get(include=["metadatas"])
        for m in (all_meta.get("metadatas") or []):
            if m:
                doc_id = m.get("doc_id")
                if doc_id:
                    doc_ids.add(doc_id)
    except Exception:
        pass
    return {"chunk_count": total, "document_count": len(doc_ids)}


def get_document_chunks(library_id: int, doc_id: str) -> List[Dict[str, Any]]:
    """返回指定文档在 Chroma 中的全部切片。"""
    col = get_collection(library_id)
    res = col.get(where={"doc_id": doc_id}, include=["documents", "metadatas"])
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    ids = res.get("ids") or []
    out = []
    for i, d in enumerate(docs):
        m = metas[i] if i < len(metas) else {}
        out.append({
            "id": ids[i] if i < len(ids) else f"{doc_id}_{i}",
            "text": d,
            "snippet": m.get("snippet", d[:200]) if m else d[:200],
            "filename": m.get("filename", "") if m else "",
        })
    return out

