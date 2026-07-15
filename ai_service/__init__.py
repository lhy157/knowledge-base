"""多模型统一接入服务（ai_service）。

与 kb 知识库服务（app/）相互独立：各自是独立模块、独立端口、独立进程。
对外接口：POST /generate、POST /doubao_chat、GET /providers（URL 保持不变）。
"""
from ai_service.main import app

__all__ = ["app"]
