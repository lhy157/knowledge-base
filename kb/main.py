"""FastAPI 入口。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kb.config import settings
from kb.routers import document, chat

app = FastAPI(title="企业知识库智能助手", version="1.0.0")

# 本服务由 Java aicontent 内部调用，放行跨域便于本地联调
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(document.router)
app.include_router(chat.router)


@app.get("/kb/health")
def health():
    return {"status": "ok", "service": "kb-server", "port": settings.kb_port}


def main():
    """命令行入口：pip install 后可直接执行 `kb-server` 启动。

    默认仅监听 127.0.0.1：知识库服务不解析 JWT、无鉴权，必须由 Java aicontent
    在内网转发调用，绝不可直接暴露公网。多机/容器部署时改为绑定内网网卡，
    并通过安全组/防火墙限制仅 aicontent 可访问 8002 端口。
    """
    import uvicorn

    uvicorn.run("kb.main:app", host="127.0.0.1", port=settings.kb_port)


if __name__ == "__main__":
    main()
