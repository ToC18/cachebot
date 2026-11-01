import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from aiogram.types import MenuButtonWebApp, WebAppInfo
import uvicorn

from app.config import settings
from app.database.session import init_models
from app.bot.bot_app import create_bot, create_dispatcher
from app.scheduler.jobs import setup_scheduler
from app.services.redis_service import redis_client
from app.api.web_app import router as web_app_router
from app.bot.keyboards import get_main_reply_keyboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("cachebot")

PRIMARY_USER_ID = 695020439

bot = create_bot()
dp = create_dispatcher()
scheduler = setup_scheduler(bot)

# Event loop of the running server (used by start_all.py to push new tunnel URLs)
main_loop: asyncio.AbstractEventLoop | None = None


async def apply_webapp_url(url: str, notify: bool = True):
    """Point the Telegram menu button (and reply keyboard) at the given Mini App URL."""
    settings.webapp_url = url
    if not url.startswith("https://"):
        logger.info("WebApp URL is not HTTPS. Telegram Menu Button omitted until HTTPS is set.")
        return

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="📱 Приложение",
                web_app=WebAppInfo(url=url)
            )
        )
        logger.info(f"Telegram Menu Button configured with URL: {url}")
    except Exception as e:
        logger.warning(f"Could not set chat menu button: {e}")

    if not notify:
        return

    # Send updated keyboard to primary user so the button on the phone is refreshed immediately
    try:
        await bot.send_message(
            chat_id=PRIMARY_USER_ID,
            text="🚀 **Сервер и Mini App запущены!**\n\nНажми кнопку **«📱 Открыть Mini App»** внизу или кнопку **«📱 Приложение»** слева от поля ввода, чтобы открыть актуальную версию.",
            reply_markup=get_main_reply_keyboard(),
            parse_mode="Markdown"
        )
        logger.info(f"Sent startup keyboard refresh message to {PRIMARY_USER_ID}")
    except Exception as e:
        logger.warning(f"Could not send startup keyboard notification: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop
    main_loop = asyncio.get_running_loop()

    logger.info("Initializing database models...")
    try:
        await init_models()
        logger.info("Database models verified.")
    except Exception as e:
        logger.warning(f"Could not initialize DB tables on start: {e}")

    logger.info("Starting scheduler...")
    scheduler.start()

    await apply_webapp_url(settings.webapp_url)

    logger.info("Starting bot polling task...")
    polling_task = asyncio.create_task(dp.start_polling(bot))

    yield

    logger.info("Shutting down...")
    main_loop = None
    scheduler.shutdown(wait=False)
    await dp.stop_polling()
    await bot.session.close()
    await redis_client.close()
    polling_task.cancel()


app = FastAPI(
    title="CacheBot API & Telegram Service",
    description="Zero-Based Budgeting Financial Mentor with Telegram Mini App & Gemini Engine",
    version="1.0.0",
    lifespan=lifespan
)

# Compress responses (chart.js 210KB -> ~70KB) - important for slow mobile tunnels
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Mount WebApp routes and static assets
app.include_router(web_app_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app_env": settings.app_env,
        "currency": settings.default_currency,
        "webapp_url": settings.webapp_url
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
