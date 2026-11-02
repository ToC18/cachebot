import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from decimal import Decimal

DEFAULT_NEON_DB = "postgresql://neondb_owner:npg_XGcNPU3dfQi1@ep-falling-scene-b90cwx8b.c-7.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


def get_active_database_url() -> str:
    # 1. Prioritize custom DB_URL or NEON_DB_URL
    if os.environ.get("DB_URL"):
        return os.environ["DB_URL"].strip()
    if os.environ.get("NEON_DB_URL"):
        return os.environ["NEON_DB_URL"].strip()

    # 2. Check standard DATABASE_URL, but ignore Replit's dummy internal 'helium' database
    db_env = (os.environ.get("DATABASE_URL") or "").strip()
    if db_env and "helium" not in db_env and "localhost" not in db_env:
        return db_env

    # 3. Always fallback to our persistent Neon PostgreSQL database
    return DEFAULT_NEON_DB


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(default="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567", alias="BOT_TOKEN")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")

    database_url: str = Field(default_factory=get_active_database_url, alias="DB_URL")
    redis_url: str = Field(default=os.environ.get("REDIS_URL", ""), alias="REDIS_URL")

    webapp_url: str = Field(default="http://localhost:8000/app", alias="WEBAPP_URL")
    tunnel_provider: str = Field(default="localhostrun", alias="TUNNEL_PROVIDER")

    app_env: str = Field(default="production", alias="APP_ENV")
    default_currency: str = Field(default="BYN", alias="DEFAULT_CURRENCY")
    monthly_hours: int = Field(default=168, alias="MONTHLY_HOURS")
    default_savings_percent: Decimal = Field(default=Decimal("20.0"), alias="DEFAULT_SAVINGS_PERCENT")


settings = Settings()
