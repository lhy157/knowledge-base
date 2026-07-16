"""腾讯云向量数据库后端：服务端内置 embedding（默认 multilingual-e5-base）。

与 Chroma 后端的差异：
- 嵌入在腾讯云向量库服务端完成，无需客户端调用 embedding 模型；
- 写入时只传文本字段（text），向量库自动用内置模型生成向量；
- 检索时传查询文本（embedding_items），服务端完成向量化与相似度计算；
- 多租户隔离：每个 library_id 对应一个 collection（kb_{library_id}），在同一 database 下互不干扰。

依赖：pip install tcvectordb
"""
from typing import List, Dict, Any, Optional

from kb.config import settings


_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            from tcvectordb import VectorDBClient
        except ImportError:
            raise RuntimeError(
                "未安装腾讯云向量库 SDK。请执行 `pip install tcvectordb`，"
                "或在 .env 中将 VECTOR_BACKEND 设为 chroma。"
            )
        _client = VectorDBClient(
            url=settings.tencent_vector_url,
            username=settings.tencent_vector_username,
            key=settings.tencent_vector_key,
            timeout=settings.tencent_vector_timeout,
            pool_size=settings.tencent_vector_pool_size,
        )
    return _client


def _get_db():
    client = _get_client()
    # 幂等：database 不存在则创建，存在则直接返回
    return client.create_database_if_not_exists(
        database_name=settings.tencent_vector_database
    )


def collection_name(library_id: int) -> str:
    return f"kb_{library_id}"


def _build_embedding():
    from tcvectordb.model.collection import Embedding
    from tcvectordb.model.enum import EmbeddingModel

    # 模型名映射到枚举（兼容大小写/连字符写法）
    # 注意：EmbeddingModel 仅含 BGE_BASE_ZH / E5_LARGE_V2 / M3E_BASE /
    #       MULTILINGUAL_E5_BASE / TEXT2VEC_LARGE_CHINESE，无 BGE_LARGE_ZH
    model_map = {
        "multilingual-e5-base": EmbeddingModel.MULTILINGUAL_E5_BASE,
        "bge-base-zh-v1.5": EmbeddingModel.BGE_BASE_ZH,
        "m3e-base": EmbeddingModel.M3E_BASE,
        "e5-large-v2": EmbeddingModel.E5_LARGE_V2,
        "text2vec-large-chinese": EmbeddingModel.TEXT2VEC_LARGE_CHINESE,
    }
    model = model_map.get(settings.tencent_embedding_model, EmbeddingModel.MULTILINGUAL_E5_BASE)
    return Embedding(
        vector_field="vector",
        field="text",
        model=model,
    )


def _build_index():
    from tcvectordb.model.index import Index, VectorIndex, FilterIndex, HNSWParams
    from tcvectordb.model.enum import FieldType, IndexType, MetricType

    return Index(
        VectorIndex(
            name="vector",
            dimension=settings.tencent_vector_dim,
            index_type=IndexType.HNSW,
            metric_type=MetricType.IP,
            params=HNSWParams(m=16, efconstruction=200),
        ),
        # 主键字段（腾讯云向量库要求每个 collection 有名为 id 的主键）
        FilterIndex(name="id", field_type=FieldType.String, index_type=IndexType.PRIMARY_KEY),
        FilterIndex(name="doc_id", field_type=FieldType.String, index_type=IndexType.FILTER),
        FilterIndex(name="filename", field_type=FieldType.String, index_type=IndexType.FILTER),
    )


def _get_collection(library_id: int):
    db = _get_db()
    return db.create_collection_if_not_exists(
        name=collection_name(library_id),
        shard=settings.tencent_vector_shard_num,
        replicas=settings.tencent_vector_replica_num,
        description=f"knowledge base {library_id}",
        embedding=_build_embedding(),
        index=_build_index(),
    )


def add_chunks(library_id: int, chunks: List[Dict[str, Any]]):
    if not chunks:
        return
    coll = _get_collection(library_id)
    # 仅传文本与元数据，向量由腾讯云服务端内置模型生成
    data = [
        {
            "id": c["id"],
            "text": c["text"],
            "doc_id": c["doc_id"],
            "filename": c["filename"],
        }
        for c in chunks
    ]
    coll.upsert(documents=data)


def query(library_id: int, text: str, top_k: int) -> List[Dict[str, Any]]:
    """按文本检索。服务端内置 embedding 完成向量化与相似度计算。

    说明：当前 tcvectordb(2.1.1) 高层的 coll.search() 在 vectors 传文本时
    仍被服务端当作普通向量检索（要求向量数组），无法触发 AI 文本检索路径；
    而其底层 post 使用 embeddingItems + ai=True 可正确走服务端 embedding 检索，
    这与 Java 侧 TencentVectorService 的 embeddingItems 用法一致，因此此处直接
    调用底层 AI 检索接口。
    """
    coll = _get_collection(library_id)
    body = {
        "database": coll.database_name,
        "collection": coll.conn_name,
        "search": {
            "embeddingItems": [text],
            "limit": top_k,
            "retrieveVector": False,
        },
    }
    try:
        # 注意：此处依赖 tcvectordb 私有底层接口（见上方 docstring 说明），
        # 已锁定 requirements.txt 中 tcvectordb==2.1.1；SDK 升级后需重新验证。
        res = coll._conn.post("/document/search", body, None, ai=True)
    except Exception as e:
        raise RuntimeError(f"腾讯云向量检索失败（底层接口异常）：{e}")
    rb = res.body if hasattr(res, "body") else res
    if not isinstance(rb, dict):
        return []
    # 业务错误码优先于空结果：code 非 0 表示检索失败，需显式抛出
    if rb.get("code") not in (None, 0, "0"):
        raise RuntimeError(f"腾讯云向量检索返回错误：code={rb.get('code')} msg={rb.get('msg')}")
    docs = rb.get("documents", []) or []
    if not isinstance(docs, list) or not docs:
        return []
    hits = docs[0] if docs else []
    if not isinstance(hits, list):
        return []
    out = []
    for item in hits:
        if not isinstance(item, dict):
            continue
        text_val = item.get("text", "")
        out.append(
            {
                "text": text_val,
                "filename": item.get("filename", ""),
                "snippet": text_val[:200],
            }
        )
    return out


def delete_document(library_id: int, doc_id: str):
    coll = _get_collection(library_id)
    coll.delete(filter=f'doc_id="{doc_id}"')


def delete_library(library_id: int):
    """删除整个知识库对应的 collection（向量 + 元数据全清）；不存在时忽略。"""
    try:
        _get_db().drop_collection(name=collection_name(library_id))
    except Exception:
        pass


def count_chunks(library_id: int) -> int:
    try:
        return get_library_stats(library_id)["chunk_count"]
    except Exception:
        return 0


def get_library_stats(library_id: int) -> Dict[str, Any]:
    """返回知识库统计：向量总条数、按 doc_id 聚合的文档数。"""
    coll = _get_collection(library_id)
    total = 0
    doc_ids = set()
    offset = 0
    limit = 1000
    try:
        while True:
            rows = coll.query(limit=limit, offset=offset, retrieve_vector=False)
            if not rows:
                break
            total += len(rows)
            for r in rows:
                did = r.get("doc_id") if isinstance(r, dict) else None
                if did:
                    doc_ids.add(did)
            if len(rows) < limit:
                break
            offset += limit
    except Exception:
        pass
    return {"chunk_count": total, "document_count": len(doc_ids)}


def get_document_chunks(library_id: int, doc_id: str) -> List[Dict[str, Any]]:
    """返回指定文档的全部切片。"""
    coll = _get_collection(library_id)
    rows = coll.query(filter=f'doc_id="{doc_id}"', limit=1000, retrieve_vector=False)
    out = []
    for i, r in enumerate(rows or []):
        text_val = r.get("text", "")
        out.append({
            "id": r.get("id", f"{doc_id}_{i}"),
            "text": text_val,
            "snippet": text_val[:200],
            "filename": r.get("filename", ""),
        })
    return out
