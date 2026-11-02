import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from decimal import Decimal


DEFAULT_NEON_DB = "postgresql://neondb_owner:npg_XGcNPU3dfQi1@ep-falling-scene-b90cwx8b.c-7.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(default="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567", alias="BOT_TOKEN")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    database_url: str = Field(
        default=os.environ.get("DB_URL") or os.environ.get("NEON_DB_URL") or os.environ.get("DATABASE_URL") or DEFAULT_NEON_DB,
        alias="DB_URL"
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    webapp_url: str = Field(default="http://localhost:8000/app", alias="WEBAPP_URL")
    tunnel_provider: str = Field(default="localhostrun", alias="TUNNEL_PROVIDER")

    app_env: str = Field(default="production", alias="APP_ENV")
    default_currency: str = Field(default="BYN", alias="DEFAULT_CURRENCY")
    monthly_hours: int = Field(default=168, alias="MONTHLY_HOURS")
    default_savings_percent: Decimal = Field(default=Decimal("20.0"), alias="DEFAULT_SAVINGS_PERCENT")


settings = Settings()
