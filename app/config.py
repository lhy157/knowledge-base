"""全局配置：从环境变量 / .env 读取。"""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 始终基于本文件所在目录定位 .env，避免运行时工作目录不同导致加载失败
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    qwen_api_key: str = ""
    kb_port: int = 8002
    chroma_dir: str = "./chroma_data"
    llm_model: str = "qwen-turbo"
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1024  # text-embedding-v3 默认维度；通过 llm.embed(..., dimensions=...) 传入
    retrieve_top_k: int = 5

    @property
    def dashscope_base(self) -> str:
        # 通义百炼 OpenAI 兼容端点
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"


settings = Settings()
