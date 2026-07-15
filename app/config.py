"""全局配置：从环境变量 / .env 读取。"""
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 始终基于本文件所在目录定位 .env，避免运行时工作目录不同导致加载失败
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    dashscope_api_key: str = ""
    kb_port: int = 8002
    chroma_dir: str = "./chroma_data"
    llm_model: str = "qwen-turbo"
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024  # text-embedding-v3 默认维度；通过 llm.embed(..., dimensions=...) 传入
    retrieve_top_k: int = 5

    @field_validator("embedding_dim")
    @classmethod
    def _validate_embed_dim(cls, v: int) -> int:
        # 通义 text-embedding-v3 合法维度：[64,128,256,512,768,1024]，非法值回退 1024 避免 500
        if v not in {64, 128, 256, 512, 768, 1024}:
            return 1024
        return v

    @property
    def dashscope_base(self) -> str:
        # 通义百炼 OpenAI 兼容端点
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"


settings = Settings()
