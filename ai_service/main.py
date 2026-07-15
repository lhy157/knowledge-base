"""多模型统一接入服务（ai_service）FastAPI 入口。

独立模块、独立端口（默认 8000，见 ai_service.config），与 kb 知识库服务（kb/）互不干扰。
对外接口保持原有 URL 不变：
    POST /generate      统一生成（流式 SSE / 非流式，可指定任意厂商模型）
    POST /doubao_chat  豆包专用接口（默认豆包模型）
    GET  /providers     查看已接入厂商及配置
"""
import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from ai_service.config import settings
from ai_service.providers import PROVIDERS, get_provider

app = FastAPI(title="Multi-Model AI Service")

# 本服务可能被前端 / 其他服务跨域调用，统一放行便于联调
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def parse_request_json(request: Request):
    """健壮解析请求体 JSON。

    兼容 UTF-8 / GBK / GB18030 / latin-1 多种编码来源（如 Windows 上的 Java
    程序以系统默认编码发送中文 JSON 时，UTF-8 解码会失败，这里按序兜底）。
    """
    raw = await request.body()
    if not raw:
        return {}
    text = None
    for enc in ("utf-8", "gbk", "gb18030", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:  # 理论上 latin-1 不会失败，仅作保险
        text = raw.decode("utf-8", errors="replace")
    return json.loads(text)


@app.post("/generate")
async def generate(request: Request):
    """统一生成接口（兼容流式 / 非流式）。

    请求体：{"prompt": "...", "model": "qwen-plus", "stream": true, "max_tokens": 2048}
    """
    data = await parse_request_json(request)
    prompt = data.get("prompt")
    model = data.get("model", "qwen-plus")
    stream = data.get("stream", True)
    max_tokens = data.get("max_tokens", 2048)

    if not prompt:
        return JSONResponse(status_code=400, content={"error": "prompt 不能为空"})

    provider, real_model = get_provider(model)

    if stream:
        return StreamingResponse(
            provider.stream(prompt, real_model, max_tokens=max_tokens),
            media_type="text/event-stream",
        )
    else:
        text = await provider.complete(prompt, real_model, max_tokens=max_tokens)
        return JSONResponse(content={"model": real_model, "content": text})


@app.get("/providers")
async def list_providers():
    """列出所有已接入厂商及其配置 / 获取地址。"""
    return {
        key: {
            "display": m.display,
            "sdk": m.sdk,
            "default_model": m.default_model,
            "base_url": m.base_url,
            "api_key_env": m.api_key_env,
            "console_url": m.console_url,
            "doc_url": m.doc_url,
        }
        for key, m in PROVIDERS.items()
    }


@app.post("/doubao_chat")
async def doubao_chat(request: Request):
    """豆包(火山引擎 Ark)专用接口：默认使用豆包模型，免去每次指定 model。

    请求体：{"prompt": "...", "stream": true, "max_tokens": 2048}
    前置条件：需设置环境变量 ARK_API_KEY。
    """
    data = await parse_request_json(request)
    prompt = data.get("prompt")
    stream = data.get("stream", True)
    max_tokens = data.get("max_tokens", 2048)

    if not prompt:
        return JSONResponse(status_code=400, content={"error": "prompt 不能为空"})

    doubao_meta = PROVIDERS["bytedance"]
    provider, real_model = get_provider(doubao_meta.default_model)

    if stream:
        return StreamingResponse(
            provider.stream(prompt, real_model, max_tokens=max_tokens),
            media_type="text/event-stream",
        )
    else:
        text = await provider.complete(prompt, real_model, max_tokens=max_tokens)
        return JSONResponse(content={"model": real_model, "content": text})


def main():
    """命令行入口：pip install 后可直接执行 `ai-service` 启动。"""
    import uvicorn

    uvicorn.run("ai_service.main:app", host="0.0.0.0", port=settings.ai_service_port)


if __name__ == "__main__":
    main()
