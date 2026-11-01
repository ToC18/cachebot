import io
from decimal import Decimal
from aiogram import Router, types, F, Bot
from sqlalchemy import select
from app.database.session import async_session_maker
from app.database.models import (
    User, Envelope, EnvelopeType, Transaction, TransactionType, TransactionSource
)
from app.services.vision_service import GeminiVisionService, ExtractedTransactionType
from app.services.text_parser import FreeTextParserService
from app.services.redis_service import redis_client
from app.services.smart_assistant import classify_expense
from app.bot.keyboards import get_crisis_keyboard

router = Router(name="expenses_router")
vision_service = GeminiVisionService()
text_parser_service = FreeTextParserService()


def clean_markdown_special_chars(text: str) -> str:
    if not text:
        return ""
    for char in ["_", "*", "`", "[", "]"]:
        text = text.replace(char, " ")
    return text


async def safe_edit_text(message: types.Message, text: str, reply_markup=None):
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception:
        clean_text = text.replace("**", "").replace("*", "").replace("`", "")
        await message.edit_text(clean_text, reply_markup=reply_markup, parse_mode=None)


async def safe_answer(message: types.Message, text: str, reply_markup=None):
    try:
        await message.answer(text, reply_markup=reply_markup, parse_mode="Markdown")
    except Exception:
        clean_text = text.replace("**", "").replace("*", "").replace("`", "")
        await message.answer(clean_text, reply_markup=reply_markup, parse_mode=None)


async def apply_expense(
    user_id: int,
    amount: Decimal,
    category: str,
    merchant: str = None,
    source: TransactionSource = TransactionSource.MANUAL_TEXT,
    tx_type: TransactionType = TransactionType.EXPENSE,
    is_clarification: bool = False,
    is_commute: bool = False
) -> dict:
    # Авто-классификация категории трат (фича 1)
    refined_category = classify_expense(f"{category} {merchant or ''}") if category in ["Расход", "EXPENSE", "Супермаркеты / Продукты", "Транспорт", "Услуги / Счета"] else category

    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            return {"status": "NO_USER"}

        env_stmt = select(Envelope).where(Envelope.user_id == user_id)
        envelopes = {e.type: e for e in (await session.execute(env_stmt)).scalars().all()}

        target_env = None
        if is_commute and EnvelopeType.COMMUTE in envelopes:
            target_env = envelopes[EnvelopeType.COMMUTE]
            target_env.current_balance = max(target_env.current_balance - amount, Decimal("0.00"))
        elif tx_type == TransactionType.EXPENSE and EnvelopeType.DAILY_SAFE_SPEND in envelopes:
            target_env = envelopes[EnvelopeType.DAILY_SAFE_SPEND]
            target_env.current_balance = max(target_env.current_balance - amount, Decimal("0.00"))

        tx = Transaction(
            user_id=user_id,
            envelope_id=target_env.id if target_env else None,
            amount=amount,
            type=tx_type,
            source=source,
            category=refined_category,
            merchant=merchant,
            is_needs_clarification=is_clarification
        )
        session.add(tx)
        await session.commit()

        overspent = Decimal("0.00")
        is_crisis = False
        today_spent = Decimal("0.00")
        
        if tx_type == TransactionType.EXPENSE and not is_commute:
            today_spent = await redis_client.add_today_spent(user_id, amount)
            if user.daily_safe_spend_limit > 0 and today_spent > user.daily_safe_spend_limit:
                overspent = today_spent - user.daily_safe_spend_limit
                is_crisis = True
                await redis_client.set_crisis_state(user_id, overspent)

        return {
            "status": "OK",
            "today_spent": today_spent,
            "daily_limit": user.daily_safe_spend_limit,
            "is_crisis": is_crisis,
            "overspent": overspent,
            "is_commute": is_commute,
            "category": refined_category,
            "target_env_balance": target_env.current_balance if target_env else None
        }


@router.message(F.photo)
async def handle_photo_expense(message: types.Message, bot: Bot):
    status_msg = await message.answer("🔍 Анализирую чек / выписку...")
    
    photo = message.photo[-1]
    photo_file = await bot.get_file(photo.file_id)
    photo_bytes_io = await bot.download_file(photo_file.file_path)
    photo_bytes = photo_bytes_io.read()

    try:
        analysis = await vision_service.analyze_image(photo_bytes)
    except Exception as e:
        await safe_edit_text(status_msg, f"⚠️ Ошибка распознавания изображения: {str(e)}")
        return

    if not analysis.items:
        await safe_edit_text(status_msg, "ℹ️ Не удалось обнаружить финансовые операции на этом фото.")
        return

    user_id = message.from_user.id
    results_text = [f"📸 **Распознан документ: {analysis.document_type}**\n"]

    for item in analysis.items:
        amount_dec = item.decimal_amount
        merchant_clean = clean_markdown_special_chars(item.merchant)
        category_clean = clean_markdown_special_chars(item.category)
        
        is_commute = item.type == ExtractedTransactionType.COMMUTE_EXPENSE
        mapped_type = TransactionType.EXPENSE
        if item.type == ExtractedTransactionType.TRANSFER_TO_CASH:
            mapped_type = TransactionType.TRANSFER_TO_CASH
        elif item.type == ExtractedTransactionType.INCOME:
            mapped_type = TransactionType.INCOME

        res = await apply_expense(
            user_id=user_id,
            amount=amount_dec,
            category=category_clean,
            merchant=merchant_clean,
            source=TransactionSource.VISION_RECEIPT if analysis.document_type == "RECEIPT" else TransactionSource.VISION_BANK_STATEMENT,
            tx_type=mapped_type,
            is_clarification=item.needs_clarification,
            is_commute=is_commute
        )

        cat_display = res.get("category", category_clean)
        if mapped_type == TransactionType.TRANSFER_TO_CASH:
            results_text.append(f"🏧 Снятие наличных: **{amount_dec} BYN** (не снижает дневной лимит)")
        elif is_commute:
            results_text.append(f"🚆 Проезд: **{amount_dec} BYN** ({merchant_clean or 'Транспорт'}) — списано из транспортного конверта")
        elif item.needs_clarification:
            results_text.append(f"❓ **{amount_dec} BYN** — {merchant_clean or 'ЕРИП/Счет'} (требуется уточнение)")
        else:
            merchant_info = f" ({merchant_clean})" if merchant_clean else ""
            results_text.append(f"🛒 **{amount_dec} BYN** — {cat_display}{merchant_info}")

        if res.get("is_crisis"):
            await status_msg.delete()
            crisis_msg = (
                f"🚨 **Внимание: Превышен дневной Safe-to-Spend лимит!**\n\n"
                f"Твой лимит: {res['daily_limit']} BYN\n"
                f"Потрачено сегодня: {res['today_spent']} BYN\n"
                f"Перерасход: **+{res['overspent']} BYN**\n\n"
                f"Без паники! Выбери, как сбалансировать бюджет:"
            )
            await safe_answer(
                message,
                "\n".join(results_text) + "\n\n" + crisis_msg,
                reply_markup=get_crisis_keyboard(res["overspent"])
            )
            return

    results_text.append("\n📈 _Диаграмму всех трат по категориям смотри в «🌟 Функции» -> «Диаграмма трат»_")
    await safe_edit_text(status_msg, "\n".join(results_text))


@router.message(F.voice)
async def handle_voice_expense(message: types.Message, bot: Bot):
    status_msg = await message.answer("🎙 Слушаю голосовое сообщение...")
    voice_file = await bot.get_file(message.voice.file_id)
    voice_bytes_io = await bot.download_file(voice_file.file_path)
    voice_bytes = voice_bytes_io.read()

    if not vision_service.api_key:
        await safe_edit_text(status_msg, "⚠️ Для распознавания аудио требуется GEMINI_API_KEY в .env")
        return

    import google.generativeai as genai
    model = genai.GenerativeModel("gemini-3.8-flash")
    try:
        response = await model.generate_content_async([
            {"mime_type": "audio/ogg", "data": voice_bytes},
            "Расшифруй голос на русском языке в точный текст трат пользователя без лишних слов."
        ])
        transcribed_text = response.text.strip()
    except Exception as e:
        await safe_edit_text(status_msg, f"⚠️ Ошибка обработки аудио: {str(e)}")
        return

    await status_msg.delete()
    await _process_text_expenses(message, transcribed_text, source=TransactionSource.VOICE_WHISPER)


@router.message(F.text & ~F.text.startswith("/") & ~F.text.startswith("?") & ~F.text.lower().startswith("купить"))
async def handle_free_text_expense(message: types.Message):
    await _process_text_expenses(message, message.text, source=TransactionSource.MANUAL_TEXT)


async def _process_text_expenses(message: types.Message, raw_text: str, source: TransactionSource):
    items = await text_parser_service.parse_text(raw_text)
    if not items:
        return

    user_id = message.from_user.id
    responses = []

    for item in items:
        amount = item["amount"]
        category = clean_markdown_special_chars(item["category"])
        desc = clean_markdown_special_chars(item["description"])

        is_commute = category == "Транспорт" and any(w in desc.lower() for w in ["маршрутк", "электричк", "автобус"])
        res = await apply_expense(
            user_id=user_id,
            amount=amount,
            category=category,
            merchant=desc,
            source=source,
            is_commute=is_commute
        )

        if res["status"] == "NO_USER":
            await safe_answer(message, "⚠️ Сначала инициализируй бюджет командой `/salary <сумма>`")
            return

        cat_display = res.get("category", category)
        if is_commute:
            responses.append(f"🚆 **{amount} BYN** ({desc}) — списано из транспортного конверта")
        else:
            responses.append(f"✅ Записано: **{amount} BYN** — {desc} ({cat_display})")

        if res.get("is_crisis"):
            crisis_msg = (
                f"\n\n🚨 **Перерасход дневного лимита!**\n"
                f"Лимит на день: {res['daily_limit']} BYN\n"
                f"Всего потрачено сегодня: {res['today_spent']} BYN\n"
                f"Перерасход: **+{res['overspent']} BYN**\n\n"
                f"Как сбалансировать систему?"
            )
            await safe_answer(
                message,
                "\n".join(responses) + crisis_msg,
                reply_markup=get_crisis_keyboard(res["overspent"])
            )
            return

    await safe_answer(message, "\n".join(responses))
