from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    BOT_TOKEN: str
    GLADIA_API_KEY: str
    DEBUG: Optional[bool] = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
