"""Chroma 向量库封装：按 library_id 建独立 collection，实现多租户隔离。"""
import os

import chromadb

from app.config import settings
from app.llm import embed


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


def add_chunks(library_id: int, chunks: list[dict]):
    if not chunks:
        return
    col = get_collection(library_id)
    texts = [c["text"] for c in chunks]
    embeddings = embed(texts)  # 显式走通义 text-embedding-v3（1024 维）
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


def query(library_id: int, vector: list[float], top_k: int) -> list[dict]:
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
