"""多模型接入：厂商配置、Provider 抽象、OpenAI 兼容实现、Anthropic 实现、工厂路由。

支持厂商：阿里-通义千问、腾讯-混元、豆包(火山引擎)、DeepSeek、OpenAI、Anthropic-Claude。

环境变量约定（与 kb 服务共享根目录 .env，统一用各厂商官方变量名）：
    DASHSCOPE_API_KEY  阿里通义（kb 的 qwen 对话 / text-embedding-v3 也用同一个 DashScope key）
    HUNYUAN_API_KEY   腾讯混元
    ARK_API_KEY        豆包 / 火山引擎
    DEEPSEEK_API_KEY   DeepSeek
    OPENAI_API_KEY     OpenAI
    ANTHROPIC_API_KEY  Anthropic Claude
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator

# OpenAI 官方异步 SDK：阿里/腾讯/豆包/DeepSeek/OpenAI 全部复用（OpenAI 兼容接口）
from openai import AsyncOpenAI

# Anthropic 官方异步 SDK（Claude）。未安装时置为 None，运行时按需提示。
try:
    from anthropic import AsyncAnthropic
except ImportError:
    AsyncAnthropic = None


@dataclass
class ProviderMeta:
    key: str                 # 内部标识
    display: str             # 中文显示名
    sdk: str                 # "openai" 或 "anthropic"
    api_key_env: str         # 读取密钥的环境变量名（各厂商官方变量名）
    base_url: str            # API 基地址（OpenAI 兼容）
    default_model: str       # 默认模型名
    console_url: str         # 控制台 / 获取 API Key 的地址
    doc_url: str             # 接口文档地址


PROVIDERS: dict[str, ProviderMeta] = {
    # ---------------- 1. 阿里 通义千问 ----------------
    "alibaba": ProviderMeta(
        key="alibaba",
        display="阿里-通义千问",
        sdk="openai",
        api_key_env="DASHSCOPE_API_KEY",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        default_model="qwen-plus",
        console_url="https://dashscope.console.aliyun.com/",
        doc_url="https://help.aliyun.com/zh/dashscope/developer-reference/quick-start",
    ),
    # ---------------- 2. 腾讯 混元 ----------------
    "tencent": ProviderMeta(
        key="tencent",
        display="腾讯-混元",
        sdk="openai",
        api_key_env="HUNYUAN_API_KEY",
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
        default_model="hunyuan-turbo",
        console_url="https://console.cloud.tencent.com/hunyuan",
        doc_url="https://cloud.tencent.com/document/product/1729",
    ),
    # ---------------- 3. 豆包（火山引擎 Ark） ----------------
    "bytedance": ProviderMeta(
        key="bytedance",
        display="豆包-火山引擎",
        sdk="openai",
        api_key_env="ARK_API_KEY",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        default_model="doubao-seed-2-0-pro-260215",
        console_url="https://console.volcengine.com/ark",
        doc_url="https://www.volcengine.com/docs/82379/",
    ),
    # ---------------- 4. DeepSeek ----------------
    "deepseek": ProviderMeta(
        key="deepseek",
        display="DeepSeek",
        sdk="openai",
        api_key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        default_model="deepseek-chat",
        console_url="https://platform.deepseek.com/",
        doc_url="https://api-docs.deepseek.com/zh-cn/",
    ),
    # ---------------- 5. OpenAI（GPT / Codex） ----------------
    "openai": ProviderMeta(
        key="openai",
        display="OpenAI",
        sdk="openai",
        api_key_env="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        console_url="https://platform.openai.com/",
        doc_url="https://platform.openai.com/docs/api-reference",
    ),
    # ---------------- 6. Anthropic（Claude / Claude Code） ----------------
    "anthropic": ProviderMeta(
        key="anthropic",
        display="Anthropic-Claude",
        sdk="anthropic",
        api_key_env="ANTHROPIC_API_KEY",
        base_url="https://api.anthropic.com",
        default_model="claude-sonnet-4-0",
        console_url="https://console.anthropic.com/",
        doc_url="https://docs.anthropic.com/en/api/messages",
    ),
}


class BaseProvider(ABC):
    """所有厂商 Provider 的抽象基类，定义统一对外接口。"""

    def __init__(self, meta: ProviderMeta):
        self.meta = meta

    @abstractmethod
    async def stream(self, prompt: str, model: str, **kwargs) -> AsyncGenerator[str, None]:
        """流式生成，逐块 yield SSE 格式字符串（data: {...}\n\n）。"""
        ...

    @abstractmethod
    async def complete(self, prompt: str, model: str, **kwargs) -> str:
        """非流式生成，一次性返回完整文本。"""
        ...


class OpenAICompatibleProvider(BaseProvider):
    """适用于所有提供 OpenAI 兼容 Chat Completions 接口的厂商。"""

    def __init__(self, meta: ProviderMeta):
        super().__init__(meta)
        api_key = os.getenv(meta.api_key_env, "")
        self.client = AsyncOpenAI(api_key=api_key, base_url=meta.base_url)

    async def stream(self, prompt: str, model: str, **kwargs) -> AsyncGenerator[str, None]:
        try:
            stream = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield f"data: {json.dumps({'content': delta.content}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'[{self.meta.display}] {e}'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    async def complete(self, prompt: str, model: str, **kwargs) -> str:
        resp = await self.client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            stream=False,
            **kwargs,
        )
        return resp.choices[0].message.content or ""


class AnthropicProvider(BaseProvider):
    """Claude 使用 Anthropic 原生 Messages 接口（非 OpenAI 兼容）。"""

    def __init__(self, meta: ProviderMeta):
        super().__init__(meta)
        if AsyncAnthropic is None:
            raise RuntimeError("未安装 anthropic SDK，请执行: pip install anthropic")
        api_key = os.getenv(meta.api_key_env, "")
        self.client = AsyncAnthropic(api_key=api_key, base_url=meta.base_url)

    async def stream(self, prompt: str, model: str, **kwargs) -> AsyncGenerator[str, None]:
        try:
            async with self.client.messages.stream(
                model=model,
                max_tokens=kwargs.get("max_tokens", 4096),
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    yield f"data: {json.dumps({'content': text}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': f'[{self.meta.display}] {e}'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

    async def complete(self, prompt: str, model: str, **kwargs) -> str:
        resp = await self.client.messages.create(
            model=model,
            max_tokens=kwargs.get("max_tokens", 4096),
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in resp.content if block.type == "text")


# 模型前缀 -> 厂商 key 的路由表，新增模型只需在此补充。
MODEL_PREFIX_ROUTING = {
    "qwen": "alibaba",
    "hunyuan": "tencent",
    "doubao": "bytedance",
    "deepseek": "deepseek",
    "gpt": "openai",
    "o1": "openai",
    "o3": "openai",
    "codex": "openai",
    "claude": "anthropic",
}

_provider_cache: dict[str, BaseProvider] = {}


def get_provider(model: str) -> tuple[BaseProvider, str]:
    """根据模型名解析出 (Provider 实例, 实际使用的模型名)。

    - 若 model 命中前缀路由，则路由到对应厂商并使用该 model
    - 若 model 形如 "厂商key:模型名"（如 "openai:gpt-4o"），则直接指定厂商
    """
    if ":" in model:
        provider_key, model_name = model.split(":", 1)
    else:
        provider_key = None
        model_name = model
        for prefix, pk in MODEL_PREFIX_ROUTING.items():
            if model.lower().startswith(prefix):
                provider_key = pk
                break

    if provider_key is None or provider_key not in PROVIDERS:
        provider_key = "openai"

    meta = PROVIDERS[provider_key]
    if provider_key not in _provider_cache:
        if meta.sdk == "anthropic":
            _provider_cache[provider_key] = AnthropicProvider(meta)
        else:
            _provider_cache[provider_key] = OpenAICompatibleProvider(meta)

    return _provider_cache[provider_key], model_name
