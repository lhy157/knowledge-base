"""FastAPI 入口。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import document, chat

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


if __name__ == "__main__":
    import uvicorn
    from app.config import settings

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.kb_port)
