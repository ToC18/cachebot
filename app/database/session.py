from typing import AsyncGenerator
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config import settings
from app.database.models import Base

ENUM_DEFINITIONS = [
    ("transaction_type", ["EXPENSE", "INCOME", "TRANSFER_TO_CASH", "TRANSFER_TO_SAVINGS", "REALLOCATION", "EMERGENCY_WITHDRAWAL"]),
    ("envelope_type", ["FIXED_COMMITMENT", "COMMUTE", "SAVINGS", "WEEKEND_FUND", "DAILY_SAFE_SPEND", "CONSUMABLES"]),
    ("transaction_source", ["MANUAL_TEXT", "VOICE_WHISPER", "VISION_RECEIPT", "VISION_BANK_STATEMENT"]),
    ("debt_type", ["I_OWE", "OWES_ME"]),
    ("obligation_type", ["INSTALLMENT", "CREDIT", "SUBSCRIPTION", "CONSUMABLE"]),
    ("habit_type", ["WARMUP", "WORKOUT", "WATER", "STRETCH"]),
]

def get_clean_database_url(raw_url: str) -> str:
    url = (raw_url or "").strip()
    if not url:
        return url
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parsed = urlparse(url)
    if "asyncpg" in parsed.scheme and parsed.query:
        params = parse_qs(parsed.query)
        clean_params = {}
        if "sslmode" in params or "ssl" in params:
            clean_params["ssl"] = "require"
        new_query = urlencode(clean_params)
        url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    return url

engine = create_async_engine(
    get_clean_database_url(settings.database_url),
    echo=False,
    pool_pre_ping=True
)

async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


async def init_models():
    """Initializes schema if not using external migrations."""
    async with engine.begin() as conn:
        for type_name, values in ENUM_DEFINITIONS:
            vals_sql = ", ".join(f"'{v}'" for v in values)
            sql = f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{type_name}') THEN
                        CREATE TYPE {type_name} AS ENUM ({vals_sql});
                    END IF;
                END$$;
            """
            await conn.execute(text(sql))
        await conn.run_sync(Base.metadata.create_all)
