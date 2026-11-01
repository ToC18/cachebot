"""Validation of Telegram Mini App initData.

Docs: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
The frontend sends `Telegram.WebApp.initData` in the `X-Telegram-Init-Data` header,
the server verifies its HMAC signature with the bot token and takes the user id from it.
Nobody can impersonate another user without knowing the bot token.
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Header, HTTPException

from app.config import settings

# initData is re-issued every time the Mini App is opened; allow long sessions anyway
MAX_INIT_DATA_AGE_SECONDS = 7 * 24 * 3600


class InitDataError(ValueError):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age: int = MAX_INIT_DATA_AGE_SECONDS) -> dict:
    """Return the Telegram user dict if initData is authentic, otherwise raise InitDataError."""
    if not init_data:
        raise InitDataError("empty initData")

    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError as e:
        raise InitDataError(f"malformed initData: {e}")

    received_hash = fields.pop("hash", None)
    if not received_hash:
        raise InitDataError("hash is missing")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise InitDataError("signature mismatch")

    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        raise InitDataError("bad auth_date")
    if max_age and time.time() - auth_date > max_age:
        raise InitDataError("initData expired")

    user_raw = fields.get("user")
    if not user_raw:
        raise InitDataError("user is missing")
    try:
        user = json.loads(user_raw)
    except json.JSONDecodeError:
        raise InitDataError("bad user json")
    if "id" not in user:
        raise InitDataError("user id is missing")
    return user


async def get_telegram_user(
    x_telegram_init_data: str = Header(default="", alias="X-Telegram-Init-Data"),
) -> dict:
    """FastAPI dependency: authenticated Telegram user of the current request."""
    try:
        return validate_init_data(x_telegram_init_data, settings.bot_token)
    except InitDataError as e:
        raise HTTPException(status_code=401, detail=f"Telegram auth failed: {e}")
