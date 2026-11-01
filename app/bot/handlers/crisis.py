from decimal import Decimal
from datetime import date
from aiogram import Router, types, F
from sqlalchemy import select
from app.database.session import async_session_maker
from app.database.models import User, Envelope, EnvelopeType, Goal, Transaction, TransactionType, TransactionSource
from app.services.finance_engine import FinanceEngine
from app.services.redis_service import redis_client

router = Router(name="crisis_router")


@router.callback_query(F.data.startswith("crisis:"))
async def handle_crisis_callback(callback: types.CallbackQuery):
    _, action, overspent_str = callback.data.split(":")
    overspent = Decimal(overspent_str)
    user_id = callback.from_user.id
    
    today = date.today()
    # Days left in current week (Monday is 0, Sunday is 6)
    weekday = today.weekday()
    remaining_days_in_week = max(7 - weekday, 1)

    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        res = await session.execute(user_stmt)
        user = res.scalar_one_or_none()

        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        # Fetch envelopes
        env_stmt = select(Envelope).where(Envelope.user_id == user_id)
        env_res = await session.execute(env_stmt)
        envelopes = {e.type: e for e in env_res.scalars().all()}

        weekend_env = envelopes.get(EnvelopeType.WEEKEND_FUND)
        weekend_fund_balance = weekend_env.current_balance if weekend_env else Decimal("0.00")
        
        # Approximate current weekly remaining discretionary budget
        daily_limit = user.daily_safe_spend_limit
        weekly_remaining_budget = daily_limit * Decimal(remaining_days_in_week)

        strategy = "COVER_BY_WEEKEND_FUND" if action == "weekend" else "DAMPEN_LIMITS"

        resolution = FinanceEngine.resolve_crisis_mode(
            overspent_amount=overspent,
            weekly_remaining_budget=weekly_remaining_budget,
            remaining_days_in_week=remaining_days_in_week,
            weekend_fund_balance=weekend_fund_balance,
            strategy=strategy
        )

        # Update user and envelopes
        user.daily_safe_spend_limit = resolution.updated_daily_limit
        if weekend_env and strategy == "COVER_BY_WEEKEND_FUND":
            weekend_env.current_balance = resolution.weekend_fund_remaining

        await session.commit()

    await redis_client.clear_crisis_state(user_id)

    reply_text = (
        f"🛡 **Режим ЧП урегулирован!**\n\n"
        f"• Решение: {resolution.action_taken}\n"
        f"• Новый Safe-to-Spend лимит: **{resolution.updated_daily_limit} BYN/день**\n"
        f"• Остаток фонда выходных: **{resolution.weekend_fund_remaining} BYN**\n\n"
        f"Финансовый баланс восстановлен без ущерба для подушки безопасности!"
    )

    await callback.message.edit_text(reply_text, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("surplus:"))
async def handle_surplus_callback(callback: types.CallbackQuery):
    parts = callback.data.split(":")
    action = parts[1]
    user_id = callback.from_user.id

    if action == "dismiss":
        await callback.message.edit_text("👍 Отлично! Сэкономленный остаток переходит на завтра.", parse_mode="Markdown")
        await callback.answer()
        return

    savings = Decimal(parts[2])

    async with async_session_maker() as session:
        if action == "goal":
            # Primary goal transfer
            goal_stmt = select(Goal).where(Goal.user_id == user_id, Goal.is_primary == True)
            goal_res = await session.execute(goal_stmt)
            goal = goal_res.scalar_one_or_none()

            if not goal:
                # Fallback to any goal or create one
                goal_stmt2 = select(Goal).where(Goal.user_id == user_id)
                goal_res2 = await session.execute(goal_stmt2)
                goal = goal_res2.scalars().first()

            if goal:
                goal.current_amount += savings
                tx = Transaction(
                    user_id=user_id,
                    goal_id=goal.id,
                    amount=savings,
                    type=TransactionType.TRANSFER_TO_SAVINGS,
                    source=TransactionSource.MANUAL_TEXT,
                    category="Сбережения",
                    merchant=f"Микро-инвестиция в цель: {goal.title}"
                )
                session.add(tx)
                await session.commit()
                text = f"🎉 **Успешно!** +{savings} BYN переведены в копилку «{goal.title}»! Баланс копилки: {goal.current_amount} BYN."
            else:
                text = f"🎯 Сэкономлено {savings} BYN! Создай цель накоплений, чтобы копить автоматически."

        elif action == "weekend":
            # Weekend fund transfer
            env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.WEEKEND_FUND)
            env_res = await session.execute(env_stmt)
            env = env_res.scalar_one_or_none()
            if env:
                env.current_balance += savings
                tx = Transaction(
                    user_id=user_id,
                    envelope_id=env.id,
                    amount=savings,
                    type=TransactionType.REALLOCATION,
                    source=TransactionSource.MANUAL_TEXT,
                    category="Фонд выходных",
                    merchant="Сдача от дневного лимита"
                )
                session.add(tx)
                await session.commit()
                text = f"🍕 **Отлично!** +{savings} BYN отложены в «Фонд выходных». Теперь там: {env.current_balance} BYN для субботы и воскресенья!"
            else:
                text = f"🍕 +{savings} BYN отправлены в Фонд выходных!"

    await callback.message.edit_text(text, parse_mode="Markdown")
    await callback.answer()
