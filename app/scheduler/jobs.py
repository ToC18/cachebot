from decimal import Decimal
from aiogram import Bot
from datetime import datetime, time as dtime
import pytz
from sqlalchemy import select
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.database.session import async_session_maker
from app.database.models import User, Goal, ShoppingReminder, HabitReminder
from app.services.redis_service import redis_client
from app.bot.keyboards import get_evening_surplus_keyboard

MSK_TZ = pytz.timezone("Europe/Moscow")


async def evening_micro_savings_job(bot: Bot):
    async with async_session_maker() as session:
        users_stmt = select(User).where(User.daily_safe_spend_limit > Decimal("0.00"))
        users = (await session.execute(users_stmt)).scalars().all()

        for user in users:
            today_spent = await redis_client.get_today_spent(user.id)
            if today_spent < user.daily_safe_spend_limit:
                savings = user.daily_safe_spend_limit - today_spent
                if savings < Decimal("0.50"):
                    continue

                goal_stmt = select(Goal).where(Goal.user_id == user.id, Goal.is_primary == True)
                goal = (await session.execute(goal_stmt)).scalar_one_or_none()
                goal_name = goal.title if goal else "Копилка"

                text = (
                    f"🌙 **Итоги дня: Сдача от лимита!**\n\n"
                    f"Твой дневной лимит: {user.daily_safe_spend_limit} {user.currency}\n"
                    f"Потрачено за сегодня: {today_spent} {user.currency}\n\n"
                    f"🔥 Ты сегодня сэкономил **{savings} {user.currency}**!\n"
                    f"Закинуть разницу в цель **[{goal_name}]** прямо сейчас?"
                )

                try:
                    await bot.send_message(
                        chat_id=user.id,
                        text=text,
                        reply_markup=get_evening_surplus_keyboard(savings),
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass


async def morning_drip_feed_job(bot: Bot):
    async with async_session_maker() as session:
        users_stmt = select(User).where(User.daily_safe_spend_limit > Decimal("0.00"))
        users = (await session.execute(users_stmt)).scalars().all()

        for user in users:
            await redis_client.reset_today_spent(user.id)
            text = (
                f"☀️ **Доброе утро! Твой Safe-to-Spend на сегодня:**\n\n"
                f"💰 Доступно для трат: **{user.daily_safe_spend_limit} {user.currency}**\n\n"
                f"Трать осознанно. Если сэкономишь — вечером сможешь отправить остаток в копилку!"
            )
            try:
                await bot.send_message(chat_id=user.id, text=text, parse_mode="Markdown")
            except Exception:
                pass


async def shopping_reminders_job(bot: Bot):
    now = datetime.now(MSK_TZ)
    async with async_session_maker() as session:
        stmt = select(ShoppingReminder).where(
            ShoppingReminder.is_sent == False,
            ShoppingReminder.remind_at <= now
        )
        due_reminders = (await session.execute(stmt)).scalars().all()

        for rem in due_reminders:
            text = (
                "🛒 **Напоминание о покупках в магазине!**\n\n"
                f"Твой список:\n"
                f"**{rem.items_text}**\n\n"
                "💡 Не забудь сфотографировать чек после оплаты!"
            )
            try:
                await bot.send_message(chat_id=rem.user_id, text=text, parse_mode="Markdown")
                rem.is_sent = True
            except Exception:
                pass
        await session.commit()


async def habit_reminders_job(bot: Bot):
    """Каждую минуту проверяет регулярные привычки (зарядка, тренировки, растяжка) по МСК."""
    now = datetime.now(MSK_TZ)
    current_time_slot = dtime(hour=now.hour, minute=now.minute)

    async with async_session_maker() as session:
        stmt = select(HabitReminder).where(
            HabitReminder.is_active == True,
            HabitReminder.remind_time == current_time_slot
        )
        due_habits = (await session.execute(stmt)).scalars().all()

        icons = {
            "WARMUP": "🤸‍♂️",
            "WORKOUT": "💪",
            "WATER": "💧",
            "STRETCH": "🧘‍♂️"
        }

        for h in due_habits:
            icon = icons.get(h.habit_type.value, "🏃‍♂️")
            text = (
                f"{icon} **ЗОЖ-напоминание: {h.title}**\n\n"
                "Время размяться, взбодриться и позаботиться о теле!\n"
                "Даже 10 минут активности разгонят метаболизм и поднимут фокус на весь день. Погнали? 🔥"
            )
            try:
                await bot.send_message(chat_id=h.user_id, text=text, parse_mode="Markdown")
            except Exception:
                pass


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    
    # 21:00 evening review
    scheduler.add_job(
        evening_micro_savings_job,
        trigger="cron",
        hour=21,
        minute=0,
        kwargs={"bot": bot}
    )
    
    # 08:00 morning limit issue
    scheduler.add_job(
        morning_drip_feed_job,
        trigger="cron",
        hour=8,
        minute=0,
        kwargs={"bot": bot}
    )

    # Каждую минуту — проверка напоминаний о покупках
    scheduler.add_job(
        shopping_reminders_job,
        trigger="interval",
        minutes=1,
        kwargs={"bot": bot}
    )

    # Каждую минуту — проверка напоминаний о зарядке и тренировках
    scheduler.add_job(
        habit_reminders_job,
        trigger="interval",
        minutes=1,
        kwargs={"bot": bot}
    )
    
    return scheduler
