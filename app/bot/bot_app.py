from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from app.config import settings

# Handlers
from app.bot.handlers import salary, expenses, crisis, stats, paywall, settings as bot_settings, more_features


def create_bot() -> Bot:
    return Bot(token=settings.bot_token)


def create_dispatcher() -> Dispatcher:
    # Use MemoryStorage by default in serverless/cloud environments without external Redis
    if settings.redis_url and "localhost" not in settings.redis_url:
        try:
            storage = RedisStorage.from_url(settings.redis_url)
        except Exception:
            storage = MemoryStorage()
    else:
        storage = MemoryStorage()

    dp = Dispatcher(storage=storage)

    # Register routers in priority order
    dp.include_router(salary.router)
    dp.include_router(more_features.router)  # Новые фичи (подушка, долги, обязательства, рандомайзер, покупки)
    dp.include_router(paywall.router)
    dp.include_router(crisis.router)
    dp.include_router(stats.router)
    dp.include_router(bot_settings.router)
    dp.include_router(expenses.router)

    return dp
