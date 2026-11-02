import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.gzip import GZipMiddleware
from aiogram.types import MenuButtonWebApp, WebAppInfo, Update
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


def detect_environment_webapp_url() -> str:
    """Auto-detects the public URL from Replit, Render, Railway, or explicit WEBAPP_URL."""
    if os.environ.get("WEBAPP_URL"):
        return os.environ["WEBAPP_URL"].strip()

    # Replit public production domain (uses double-dash: slug--owner.replit.app)
    slug = os.environ.get("REPL_SLUG")
    owner = os.environ.get("REPL_OWNER")
    if slug and owner:
        return f"https://{slug}--{owner}.replit.app/app?v=4.0"

    # Render.com
    render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
    if render_host:
        return f"https://{render_host}/app?v=4.0"

    return settings.webapp_url


async def apply_webapp_url(url: str, notify: bool = True):
    """Point the Telegram menu button (and reply keyboard) at the given Mini App URL."""
    settings.webapp_url = url
    if not url.startswith("https://"):
        logger.info(f"WebApp URL '{url}' is not HTTPS. Telegram Menu Button omitted until HTTPS is set.")
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

    is_serverless = bool(os.environ.get("VERCEL") or os.environ.get("USE_WEBHOOK"))

    # Auto-detect public HTTPS URL in cloud platforms like Replit
    detected_url = detect_environment_webapp_url()
    if detected_url.startswith("https://"):
        settings.webapp_url = detected_url
        logger.info(f"Detected cloud WebApp URL: {settings.webapp_url}")

    logger.info("Initializing database models...")
    try:
        await init_models()
        logger.info("Database models verified.")
    except Exception as e:
        logger.warning(f"Could not initialize DB tables on start: {e}")

    polling_task = None
    if not is_serverless:
        logger.info("Starting scheduler...")
        scheduler.start()
        await apply_webapp_url(settings.webapp_url)
        logger.info("Starting bot polling task...")
        # Drop pending webhook if switching to polling
        try:
            await bot.delete_webhook(drop_pending_updates=False)
        except Exception as e:
            logger.warning(f"Failed to delete webhook: {e}")
        polling_task = asyncio.create_task(dp.start_polling(bot))
    else:
        logger.info("Running in serverless/webhook mode. Long polling and background scheduler omitted.")

    yield

    logger.info("Shutting down...")
    main_loop = None
    if not is_serverless:
        scheduler.shutdown(wait=False)
        await dp.stop_polling()
        if polling_task:
            polling_task.cancel()
    await bot.session.close()
    await redis_client.close()


app = FastAPI(
    title="CacheBot API & Telegram Service",
    description="Zero-Based Budgeting Financial Mentor with Telegram Mini App & Gemini Engine",
    version="1.0.0",
    lifespan=lifespan
)

# Compress responses (chart.js 210KB -> ~70KB) - important for slow mobile tunnels
app.add_middleware(GZipMiddleware, minimum_size=1000)

# Mount WebApp routes
app.include_router(web_app_router)

# Mount static files with absolute path safety
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    """Processes incoming Telegram updates in serverless/webhook mode."""
    try:
        data = await request.json()
        update = Update.model_validate(data, context={"bot": bot})
        await dp.feed_update(bot=bot, update=update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error handling Telegram webhook update: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


@app.get("/api/setup-webhook")
async def setup_webhook(request: Request):
    """Configures Telegram to send all updates to this deployed Webhook URL."""
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    proto = request.headers.get("x-forwarded-proto") or "https"
    base_url = f"{proto}://{host}"
    webhook_url = f"{base_url}/api/webhook"
    mini_app_url = f"{base_url}/app?v=4.0"

    settings.webapp_url = mini_app_url
    wh_ok = await bot.set_webhook(url=webhook_url, drop_pending_updates=True)
    btn_ok = await bot.set_chat_menu_button(
        menu_button=MenuButtonWebApp(
            text="📱 Приложение",
            web_app=WebAppInfo(url=mini_app_url)
        )
    )
    return {
        "status": "configured",
        "webhook_url": webhook_url,
        "mini_app_url": mini_app_url,
        "webhook_set": wh_ok,
        "menu_button_set": btn_ok
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "app_env": settings.app_env,
        "currency": settings.default_currency,
        "webapp_url": settings.webapp_url,
        "mode": "webhook" if (os.environ.get("VERCEL") or os.environ.get("USE_WEBHOOK")) else "polling"
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
