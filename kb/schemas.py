"""Pydantic 请求模型。"""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class ChatRequest(BaseModel):
    """问答请求体。"""
    user_id: int
    library_id: int
    question: str
    history: Optional[List[Dict[str, Any]]] = None
