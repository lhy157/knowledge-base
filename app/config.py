"""全局配置：从环境变量 / .env 读取。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    qwen_api_key: str = ""
    kb_port: int = 8001
    chroma_dir: str = "./chroma_data"
    llm_model: str = "qwen-turbo"
    embedding_model: str = "text-embedding-v3"
    embedding_dim: int = 1536
    retrieve_top_k: int = 5

    @property
    def dashscope_base(self) -> str:
        # 通义百炼 OpenAI 兼容端点
        return "https://dashscope.aliyuncs.com/compatible-mode/v1"


settings = Settings()
