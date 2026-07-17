"""ai_service 配置：从项目根目录 .env 读取，与 kb 服务共享同一份 .env。"""
from pathlib import Path

# 始终基于本文件所在目录定位 .env（项目根目录），避免运行时工作目录不同导致加载失败
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"

# 关键：必须先将 .env 加载到 os.environ，否则 providers.py 中 os.getenv() 读不到值
# pydantic_settings 只把 env 注入到 Settings 属性，不会写入 os.environ
from dotenv import load_dotenv

load_dotenv(_ENV_FILE)

from pydantic_settings import BaseSettings, SettingsConfigDict


class AIServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    # ai_service 独立端口（与 kb 的 KB_PORT 互不冲突）
    ai_service_port: int = 8000


settings = AIServiceSettings()
