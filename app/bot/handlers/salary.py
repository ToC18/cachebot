import re
from datetime import date, datetime
from decimal import Decimal
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from sqlalchemy import select

from app.database.session import async_session_maker
from app.database.models import (
    User, Envelope, EnvelopeType, RecurringRule, Goal, Transaction, TransactionType, TransactionSource,
    Obligation
)
from app.services.finance_engine import FinanceEngine
from app.services.redis_service import redis_client
from app.bot.keyboards import (
    get_main_reply_keyboard, 
    get_income_type_keyboard, 
    get_payday_selection_keyboard
)
from app.bot.states import IncomeFSM

router = Router(name="salary_router")


@router.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "👋 **Привет! Я твой AI-наставник по осознанным финансам.**\n\n"
        "Я работаю по методологии **Zero-Based Budgeting** («Заплати сначала себе»):\n"
        "1. 🔒 Замораживаю обязательства (рассрочки, кредиты, абонементы, вейп, дорога).\n"
        "2. 🎯 Отправляю 20% в копилку до того, как ты успеешь потратить.\n"
        "3. 💧 Выдаю бюджет небольшими ежедневными траншами (Safe-to-Spend).\n\n"
        "**Все управление доступно через удобные кнопки внизу экрана!**\n"
        "• 💼 **Внести доход** — зарплата, аванс, премия\n"
        "• 📊 **Мой бюджет** — наглядная диаграмма и конверты\n"
        "• ⏳ **Умный Paywall** — переведи цену в часы жизни\n"
        "• 🌟 **Функции** — долги, вычет из подушки, рассрочки, рандомайзер, список покупок\n"
        "• ⚙️ **Настройки** — день зарплаты, график, % в копилку, вкл/выкл часов\n\n"
        "А также отправляй фото чеков, скрины выписок или пиши: `14 маршрутка`"
    )
    await message.answer(welcome_text, reply_markup=get_main_reply_keyboard(), parse_mode="Markdown")


@router.message(F.text == "💼 Внести доход")
async def btn_income_start(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "💼 **Внесение дохода:**\n"
        "Выбери тип начисления:",
        reply_markup=get_income_type_keyboard()
    )


@router.callback_query(F.data.startswith("income_type:"))
async def handle_income_type_selection(callback: types.CallbackQuery, state: FSMContext):
    income_type = callback.data.split(":")[1]
    await state.update_data(income_type=income_type)
    await state.set_state(IncomeFSM.waiting_for_amount)

    type_titles = {
        "full_salary": "💼 Полная зарплата (новый цикл)",
        "advance": "💸 Аванс / Часть зарплаты",
        "bonus": "🎁 Премия / Подработка"
    }
    await callback.message.edit_text(
        f"Выбрано: **{type_titles.get(income_type)}**\n\n"
        "Введи сумму начисления (например: `1500` или `2350.50`):",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "income_cancel")
async def handle_income_cancel(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Внесение дохода отменено.")
    await callback.answer()


@router.message(IncomeFSM.waiting_for_amount)
async def process_income_amount_input(message: types.Message, state: FSMContext):
    clean_val = message.text.replace(",", ".").strip()
    match = re.search(r"(\d+(?:\.\d{1,2})?)", clean_val)
    if not match:
        await message.answer("⚠️ Введи корректную сумму числом, например: `1800`")
        return

    amount = Decimal(match.group(1))
    if amount <= Decimal("0.00"):
        await message.answer("⚠️ Сумма должна быть больше нуля.")
        return

    await state.update_data(amount=str(amount))
    data = await state.get_data()
    income_type = data.get("income_type", "full_salary")

    if income_type == "full_salary":
        await state.set_state(IncomeFSM.waiting_for_payday)
        await message.answer(
            "📅 **Выбери дату следующей зарплаты / аванса:**\n"
            "Это нужно для точного расчета ежедневного лимита Safe-to-Spend.",
            reply_markup=get_payday_selection_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await _apply_income(message, state, amount=amount, income_type=income_type, target_date=None)


@router.callback_query(F.data.startswith("payday_day:"))
async def handle_payday_selection(callback: types.CallbackQuery, state: FSMContext):
    choice = callback.data.split(":")[1]
    data = await state.get_data()
    amount = Decimal(data["amount"])

    if choice == "custom":
        await state.set_state(IncomeFSM.waiting_for_custom_date)
        await callback.message.edit_text(
            "📅 **Введи точную дату следующей выплаты в формате ДД.ММ:**\n"
            "Например: `25.11` или `05.12`",
            parse_mode="Markdown"
        )
        await callback.answer()
        return

    today = date.today()
    target_date = None
    payday_day = None

    if choice != "skip":
        payday_day = int(choice)

    await callback.message.delete()
    await _apply_income(callback.message, state, amount=amount, income_type="full_salary", target_date=target_date, payday_day=payday_day)
    await callback.answer()


@router.message(IncomeFSM.waiting_for_custom_date)
async def process_custom_date_input(message: types.Message, state: FSMContext):
    text = message.text.strip()
    match = re.match(r"^(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?$", text)
    if not match:
        await message.answer("⚠️ Неверный формат даты. Введи в виде `25.11`:")
        return

    day = int(match.group(1))
    month = int(match.group(2))
    today = date.today()
    year = int(match.group(3)) if match.group(3) else today.year
    if year < 100:
        year += 2000

    try:
        target_date = date(year, month, day)
    except ValueError:
        await message.answer("⚠️ Некорректная дата. Попробуй еще раз:")
        return

    if target_date <= today:
        try:
            target_date = date(today.year + 1, month, day)
        except ValueError:
            target_date = date(today.year + 1, month, 28)

    data = await state.get_data()
    amount = Decimal(data["amount"])
    await _apply_income(message, state, amount=amount, income_type="full_salary", target_date=target_date, payday_day=target_date.day)


async def _apply_income(message: types.Message, state: FSMContext, amount: Decimal, income_type: str, target_date: date = None, payday_day: int = None):
    await state.clear()
    user_id = message.chat.id
    today = date.today()

    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            user = User(
                id=user_id,
                currency="BYN",
                monthly_working_hours=168,
                work_shifts_per_month=22,
                roundtrip_commute_fare=Decimal("0.00"),
                payday_day_of_month=payday_day or 10,
                savings_target_percent=Decimal("20.00")
            )
            session.add(user)

        if payday_day:
            user.payday_day_of_month = payday_day
        if target_date:
            user.next_payday_date = target_date

        # Суммируем активные обязательства (фича 6: кредиты, рассрочки, абонементы, расходники)
        oblg_stmt = select(Obligation).where(Obligation.user_id == user_id, Obligation.is_active == True)
        obligations = (await session.execute(oblg_stmt)).scalars().all()
        obligations_total = sum(o.monthly_amount for o in obligations)

        if income_type == "full_salary":
            res = FinanceEngine.process_salary_pipeline(
                salary=amount,
                work_shifts=user.work_shifts_per_month,
                roundtrip_commute_fare=user.roundtrip_commute_fare,
                fixed_commitments_total=obligations_total,
                savings_percent=user.savings_target_percent,
                today=today,
                payday_day=user.payday_day_of_month,
                target_date=user.next_payday_date,
                working_hours=user.monthly_working_hours
            )

            user.daily_safe_spend_limit = res.daily_safe_spend
            user.current_hourly_rate = res.hourly_rate
            user.current_cycle_net_base = res.net_base

            env_map = {
                EnvelopeType.COMMUTE: ("Транспортный фонд", res.commute_frozen),
                EnvelopeType.FIXED_COMMITMENT: ("Обязательства и счета", res.fixed_commitments_frozen),
                EnvelopeType.SAVINGS: ("Копилка / Подушка", res.savings_locked),
                EnvelopeType.DAILY_SAFE_SPEND: ("Свободный дневной бюджет", res.discretionary_budget),
                EnvelopeType.WEEKEND_FUND: ("Фонд выходных", Decimal("0.00")),
            }
            for env_type, (env_name, allocated) in env_map.items():
                env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == env_type)
                env = (await session.execute(env_stmt)).scalar_one_or_none()
                if not env:
                    env = Envelope(
                        user_id=user_id,
                        name=env_name,
                        type=env_type,
                        target_amount=allocated,
                        current_balance=allocated
                    )
                    session.add(env)
                else:
                    env.target_amount = allocated
                    env.current_balance = allocated

            await redis_client.reset_today_spent(user_id)
            await redis_client.clear_crisis_state(user_id)

            oblg_info = f"\n  • Рассрочки, кредиты, абонементы: {obligations_total} {user.currency}" if obligations_total > 0 else ""
            reply_msg = (
                "🎯 **Зарплатный цикл ZBB успешно запущен!**\n\n"
                f"💰 Доход: **{amount} {user.currency}**\n"
                f"📅 Дней в цикле: **{res.days_in_cycle}**\n\n"
                "🔒 **Заморожено (не трогаем):**\n"
                f"  • Дорога на работу: {res.commute_frozen} {user.currency}{oblg_info}\n\n"
                f"🎯 **«Заплати себе» (в копилку):** {res.savings_locked} {user.currency}\n"
                f"⏳ **Твоя ставка жизни:** {res.hourly_rate} {user.currency}/час\n\n"
                f"💧 **Твой Safe-to-Spend лимит:**\n"
                f"👉 **{res.daily_safe_spend} {user.currency} / каждый день**\n\n"
                "_Все обязательства защищены и не уменьшают твой дневной бюджет!_"
            )
        else:
            partial_res = FinanceEngine.process_partial_income(
                income_amount=amount,
                current_daily_limit=user.daily_safe_spend_limit or Decimal("0.00"),
                savings_percent=user.savings_target_percent,
                today=today,
                target_date=user.next_payday_date,
                payday_day=user.payday_day_of_month
            )
            user.daily_safe_spend_limit = partial_res.new_daily_safe_spend

            savings_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.SAVINGS)
            savings_env = (await session.execute(savings_stmt)).scalar_one_or_none()
            if savings_env:
                savings_env.current_balance += partial_res.savings_locked

            safe_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.DAILY_SAFE_SPEND)
            safe_env = (await session.execute(safe_stmt)).scalar_one_or_none()
            if safe_env:
                safe_env.current_balance += partial_res.discretionary_added

            reply_msg = (
                "💸 **Дополнительный доход распределен!**\n\n"
                f"💰 Начислено: **{amount} {user.currency}**\n"
                f"🎯 В копилку: **+{partial_res.savings_locked} {user.currency}**\n\n"
                f"💧 **Новый Safe-to-Spend лимит:**\n"
                f"👉 **{user.daily_safe_spend_limit} {user.currency} / день**"
            )

        tx = Transaction(
            user_id=user_id,
            amount=amount,
            type=TransactionType.INCOME,
            source=TransactionSource.MANUAL_TEXT,
            category="Доход / Зарплата",
            merchant=f"Пополнение ({income_type})"
        )
        session.add(tx)
        await session.commit()

    await message.answer(reply_msg, reply_markup=get_main_reply_keyboard(), parse_mode="Markdown")


@router.message(Command("salary"))
async def cmd_salary_direct(message: types.Message, state: FSMContext):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: `/salary <сумма>` (например: `/salary 1800`)", parse_mode="Markdown")
        return
    clean_val = parts[1].replace(",", ".").strip()
    match = re.search(r"(\d+(?:\.\d{1,2})?)", clean_val)
    if not match:
        await message.answer("⚠️ Введи корректную сумму числом, например: `/salary 1800`")
        return

    amount = Decimal(match.group(1))
    await _apply_income(message, state, amount=amount, income_type="full_salary")
