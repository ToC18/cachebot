import os
import sys
import uvicorn
import logging

# Ensure UTF-8 console output
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.config import settings

logger = logging.getLogger("cachebot.prod")


def configure_production_url():
    # 1. Check if WEBAPP_URL is explicitly provided
    webapp_url = os.environ.get("WEBAPP_URL", "").strip()

    # 2. Check Hugging Face Spaces auto-generated hostname
    space_host = os.environ.get("SPACE_HOST", "").strip()
    if not webapp_url and space_host:
        webapp_url = f"https://{space_host}/app?v=4.0"

    # 3. Check Render.com auto-generated hostname
    render_host = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if not webapp_url and render_host:
        webapp_url = f"https://{render_host}/app?v=4.0"

    # 4. Check Railway auto-generated domain
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    if not webapp_url and railway_domain:
        webapp_url = f"https://{railway_domain}/app?v=4.0"

    if webapp_url:
        settings.webapp_url = webapp_url
        print(f"=== Production Mini App URL: {settings.webapp_url} ===")
    else:
        print(f"=== WebApp URL fallback: {settings.webapp_url} ===")


def main():
    default_port = "7860" if os.environ.get("SPACE_ID") else "8000"
    port = int(os.environ.get("PORT", default_port))
    configure_production_url()

    from main import app
    print(f"=== Starting CacheBot Production Server on 0.0.0.0:{port} ===", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
