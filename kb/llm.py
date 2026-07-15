"""通义千问 LLM（流式）+ text-embedding-v3 向量化封装。

通过通义百炼的 OpenAI 兼容接口调用，需设置环境变量 DASHSCOPE_API_KEY。
"""
from typing import List, Dict, Any, Optional
from openai import OpenAI

from kb.config import settings

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.dashscope_api_key,
            base_url=settings.dashscope_base,
        )
    return _client


def embed(texts: List[str]) -> List[List[float]]:
    """批量文本向量化，返回同顺序的向量列表。

    通义 text-embedding-v3 单批 input 上限为 10 条，且维度必须落在
    [64,128,256,512,768,1024]，故按 10 条一批切片发送。
    """
    results: List[List[float]] = []
    for i in range(0, len(texts), 10):
        batch = texts[i:i + 10]
        resp = _get_client().embeddings.create(
            model=settings.embedding_model,
            input=batch,
            dimensions=settings.embedding_dim,
        )
        results.extend(item.embedding for item in resp.data)
    return results


def stream_chat(prompt: str, history: Optional[List[Dict[str, Any]]] = None):
    """流式对话，yield 增量文本片段。"""
    messages: List[Dict[str, Any]] = []
    if history:
        for h in history:
            role = h.get("role")
            content = h.get("content")
            if role and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    stream = _get_client().chat.completions.create(
        model=settings.llm_model,
        messages=messages,
        stream=True,
        temperature=0.3,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta

