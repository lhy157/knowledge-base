"""问答路由：SSE 流式返回 {type:'content'|'done'|'error'}。"""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from kb.rag import answer
from kb.schemas import ChatRequest

router = APIRouter(prefix="/kb", tags=["chat"])


@router.post("/chat")
def chat(req: ChatRequest):
    def event_stream():
        try:
            stream, hits = answer(req.library_id, req.question, req.history)
            for text in stream:
                yield "data: " + json.dumps(
                    {"type": "content", "text": text}, ensure_ascii=False
                ) + "\n\n"
            sources = [{"filename": h["filename"], "snippet": h["snippet"]} for h in hits]
            yield "data: " + json.dumps(
                {"type": "done", "sources": sources}, ensure_ascii=False
            ) + "\n\n"
        except Exception as e:
            yield "data: " + json.dumps(
                {"type": "error", "text": str(e)}, ensure_ascii=False
            ) + "\n\n"

    return StreamingResponse(
        event_stream(), media_type="text/event-stream; charset=utf-8"
    )
