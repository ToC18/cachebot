from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from decimal import Decimal


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str = Field(default="123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567", alias="BOT_TOKEN")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    
    database_url: str = Field(default="postgresql+asyncpg://postgres:postgres@localhost:5432/cachebot_db", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    
    webapp_url: str = Field(default="http://localhost:8000/app", alias="WEBAPP_URL")
    tunnel_provider: str = Field(default="localhostrun", alias="TUNNEL_PROVIDER")

    app_env: str = Field(default="development", alias="APP_ENV")
    default_currency: str = Field(default="BYN", alias="DEFAULT_CURRENCY")
    monthly_hours: int = Field(default=168, alias="MONTHLY_HOURS")
    default_savings_percent: Decimal = Field(default=Decimal("20.0"), alias="DEFAULT_SAVINGS_PERCENT")


settings = Settings()
