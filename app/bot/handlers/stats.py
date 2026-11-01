from decimal import Decimal
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from sqlalchemy import select, func
from app.database.session import async_session_maker
from app.database.models import User, Envelope, EnvelopeType, Transaction, TransactionType
from app.services.analytics_service import AnalyticsService
from app.services.redis_service import redis_client

router = Router(name="stats_router")


@router.message(Command("stats"))
@router.message(F.text == "📊 Мой бюджет")
async def cmd_stats(message: types.Message):
    user_id = message.from_user.id

    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            await message.answer("⚠️ Данные не найдены. Внеси зарплату через кнопку 💼 «Внести доход».", parse_mode="Markdown")
            return

        env_stmt = select(Envelope).where(Envelope.user_id == user_id)
        envelopes = {e.type: e for e in (await session.execute(env_stmt)).scalars().all()}

        commute_env = envelopes.get(EnvelopeType.COMMUTE)
        fixed_env = envelopes.get(EnvelopeType.FIXED_COMMITMENT)
        savings_env = envelopes.get(EnvelopeType.SAVINGS)
        safe_spend_env = envelopes.get(EnvelopeType.DAILY_SAFE_SPEND)
        weekend_env = envelopes.get(EnvelopeType.WEEKEND_FUND)

        commute_val = commute_env.current_balance if commute_env else Decimal("0.00")
        fixed_val = fixed_env.current_balance if fixed_env else Decimal("0.00")
        frozen_total = commute_val + fixed_val
        savings_total = savings_env.current_balance if savings_env else Decimal("0.00")
        safe_spend_balance = safe_spend_env.current_balance if safe_spend_env else Decimal("0.00")
        weekend_balance = weekend_env.current_balance if weekend_env else Decimal("0.00")

        spent_stmt = select(func.coalesce(func.sum(Transaction.amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.type == TransactionType.EXPENSE
        )
        flexible_spent = Decimal(str((await session.execute(spent_stmt)).scalar()))

    today_spent = await redis_client.get_today_spent(user_id)

    chart_bytes = AnalyticsService.generate_budget_breakdown_chart(
        frozen_obligations=frozen_total,
        savings_total=savings_total,
        flexible_spent=flexible_spent,
        safe_spend_balance=safe_spend_balance,
        currency=user.currency
    )

    caption = (
        "📊 **Аналитика твоего бюджета (ZBB):**\n\n"
        f"🔒 **Замороженные обязательства:** {frozen_total} {user.currency}\n"
        f"  • Дорога на работу: {commute_val} {user.currency}\n"
        f"  • Счета и аренда: {fixed_val} {user.currency}\n\n"
        f"🎯 **Копилка / Подушка:** {savings_total} {user.currency}\n"
        f"🍕 **Фонд выходных:** {weekend_balance} {user.currency}\n\n"
        f"💧 **Safe-to-Spend лимит:** {user.daily_safe_spend_limit} {user.currency}/день\n"
        f"💳 **Потрачено сегодня:** {today_spent} {user.currency}\n"
        f"📉 **Всего гибких трат в цикле:** {flexible_spent} {user.currency}"
    )

    photo_file = BufferedInputFile(chart_bytes, filename="budget_breakdown.png")
    await message.answer_photo(photo=photo_file, caption=caption, parse_mode="Markdown")
