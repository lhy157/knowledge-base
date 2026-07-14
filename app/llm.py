"""通义千问 LLM（流式）+ text-embedding-v3 向量化封装。

通过通义百炼的 OpenAI 兼容接口调用，需设置环境变量 QWEN_API_KEY。
"""
from openai import OpenAI

from app.config import settings

_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.qwen_api_key,
            base_url=settings.dashscope_base,
        )
    return _client


def embed(texts: list[str]) -> list[list[float]]:
    """批量文本向量化，返回同顺序的向量列表。"""
    resp = _get_client().embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    # 通义返回顺序与输入一致
    return [item.embedding for item in resp.data]


def stream_chat(prompt: str, history: list[dict] | None = None):
    """流式对话，yield 增量文本片段。"""
    messages: list[dict] = []
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
