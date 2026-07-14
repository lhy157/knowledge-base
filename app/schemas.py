"""Pydantic 请求 / 响应模型。"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class LibraryCreate(BaseModel):
    user_id: int
    name: str


class DocumentOut(BaseModel):
    doc_id: str
    library_id: int
    filename: str
    chunk_count: int
    status: str
    created_at: str


class ChatRequest(BaseModel):
    user_id: int
    library_id: int
    question: str
    history: Optional[List[Dict[str, Any]]] = None


class ChatSource(BaseModel):
    filename: str
    snippet: str
