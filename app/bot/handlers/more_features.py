"""Handler for feature buttons:
- Подушка и Долги (вычет, счетчик я должен / мне должны)
- Обязательства и Расходники (рассрочки, кредиты, абонементы, вейп)
- Диаграмма расходов по категориям
- Срок до цели
- Рандомайзер (брать или нет?)
- Список покупок с напоминанием по МСК
"""
from datetime import datetime, time as dtime
from decimal import Decimal
import pytz
import re

from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile
from sqlalchemy import select, func

from app.database.session import async_session_maker
from app.database.models import (
    User, Envelope, EnvelopeType, Goal, Transaction, TransactionType, TransactionSource,
    Debt, DebtType, Obligation, ObligationType, ShoppingReminder
)
from app.bot.keyboards import (
    MORE_FEATURES_BUTTON_TEXT,
    get_more_features_keyboard,
    get_debts_menu_keyboard,
    get_obligations_menu_keyboard,
    get_main_reply_keyboard
)
from app.bot.states import (
    DebtFSM, EmergencyWithdrawFSM, ObligationFSM, ShoppingReminderFSM, RandomizerFSM
)
from app.services.smart_assistant import classify_expense, decide_randomizer, estimate_goal_months
from app.services.analytics_service import AnalyticsService

router = Router(name="more_features_router")
MSK_TZ = pytz.timezone("Europe/Moscow")


# ---------------------------------------------------------------------------
# Главное меню «🌟 Функции»
# ---------------------------------------------------------------------------

@router.message(F.text == MORE_FEATURES_BUTTON_TEXT)
async def btn_more_features(message: types.Message):
    text = (
        "🌟 **Дополнительные финансовые функции:**\n\n"
        "• 🎯 **Подушка & Долги** — вычет при форс-мажоре, учет кто кому должен\n"
        "• 💳 **Обязательства & Вейп** — рассрочки, кредиты, регулярные расходники\n"
        "• 📈 **Диаграмма трат** — распределение расходов по категориям\n"
        "• 🎯 **Срок до цели** — прогноз в месяцах, сколько копить\n"
        "• 🎲 **Брать или нет?** — умный рандомайзер покупок с аргументами\n"
        "• ⏰ **Список покупок** — список с напоминанием в нужное время по МСК\n"
    )
    await message.answer(text, reply_markup=get_more_features_keyboard(), parse_mode="Markdown")


@router.callback_query(F.data == "features:back_main")
async def cb_back_main_features(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🌟 **Выбери нужный раздел:**",
        reply_markup=get_more_features_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# ФИЧА 2 & 8: Подушка & Долги
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "features:debts")
async def cb_debts_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with async_session_maker() as session:
        env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.SAVINGS)
        savings_env = (await session.execute(env_stmt)).scalar_one_or_none()
        savings_balance = savings_env.current_balance if savings_env else Decimal("0.00")

        debts_stmt = select(Debt).where(Debt.user_id == user_id, Debt.is_closed == False)
        active_debts = (await session.execute(debts_stmt)).scalars().all()

        i_owe_sum = sum(d.remaining_amount for d in active_debts if d.debt_type == DebtType.I_OWE)
        owes_me_sum = sum(d.remaining_amount for d in active_debts if d.debt_type == DebtType.OWES_ME)

    text = (
        "🎯 **Подушка безопасности & Долги:**\n\n"
        f"🛡 Баланс подушки: **{savings_balance} BYN**\n"
        f"🔴 Я должен: **{i_owe_sum} BYN**\n"
        f"🟢 Мне должны: **{owes_me_sum} BYN**\n\n"
        "💡 *Правило:* вычет из подушки или займ уменьшают подушку, а при следующем доходе "
        "система напомнит вернуть эту сумму обратно в копилку."
    )
    await callback.message.edit_text(text, reply_markup=get_debts_menu_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data == "debt_action:emergency_withdraw")
async def cb_emergency_withdraw_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(EmergencyWithdrawFSM.waiting_for_amount)
    await callback.message.answer(
        "💸 **Вычет из подушки безопасности**\n\n"
        "На какую сумму форс-мажор? Введи сумму (например, `150`):"
    )
    await callback.answer()


@router.message(EmergencyWithdrawFSM.waiting_for_amount)
async def process_withdraw_amount(message: types.Message, state: FSMContext):
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", message.text)
    if not match:
        await message.answer("⚠️ Введи сумму числом, например: `120`")
        return
    amount = Decimal(match.group(1).replace(",", "."))
    await state.update_data(withdraw_amount=str(amount))
    await state.set_state(EmergencyWithdrawFSM.waiting_for_reason)
    await message.answer("Укажи причину вычета (например, `ремонт зуба`, `срочная запчасть`):")


@router.message(EmergencyWithdrawFSM.waiting_for_reason)
async def process_withdraw_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    amount = Decimal(data["withdraw_amount"])
    reason = message.text.strip()
    user_id = message.from_user.id
    await state.clear()

    async with async_session_maker() as session:
        env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.SAVINGS)
        savings_env = (await session.execute(env_stmt)).scalar_one_or_none()
        if not savings_env or savings_env.current_balance < amount:
            cur = savings_env.current_balance if savings_env else Decimal("0.00")
            await message.answer(f"⚠️ В подушке недостаточно средств! Текущий баланс: **{cur} BYN**.")
            return

        savings_env.current_balance -= amount
        tx = Transaction(
            user_id=user_id,
            envelope_id=savings_env.id,
            amount=amount,
            type=TransactionType.EMERGENCY_WITHDRAWAL,
            source=TransactionSource.MANUAL_TEXT,
            category="Форс-мажор / Подушка",
            merchant=reason
        )
        session.add(tx)
        await session.commit()
        new_balance = savings_env.current_balance

    await message.answer(
        f"✅ Списано из подушки: **-{amount} BYN**\n"
        f"Причина: _{reason}_\n"
        f"🛡 Новый остаток подушки: **{new_balance} BYN**\n\n"
        f"💡 В следующем зарплатном цикле рекомендуем вернуть эту сумму обратно.",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown"
    )


# Добавление долгов
@router.callback_query(F.data.in_(["debt_action:add_i_owe", "debt_action:add_owes_me"]))
async def cb_add_debt_start(callback: types.CallbackQuery, state: FSMContext):
    is_i_owe = callback.data == "debt_action:add_i_owe"
    await state.update_data(debt_type=DebtType.I_OWE.value if is_i_owe else DebtType.OWES_ME.value)
    await state.set_state(DebtFSM.waiting_for_person)
    prompt = "Кому ты должен?" if is_i_owe else "Кто тебе должен?"
    await callback.message.answer(f"👤 {prompt} Напиши имя:")
    await callback.answer()


@router.message(DebtFSM.waiting_for_person)
async def process_debt_person(message: types.Message, state: FSMContext):
    await state.update_data(person_name=message.text.strip())
    await state.set_state(DebtFSM.waiting_for_amount)
    await message.answer("Какая сумма долга? (например: `100`):")


@router.message(DebtFSM.waiting_for_amount)
async def process_debt_amount(message: types.Message, state: FSMContext):
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", message.text)
    if not match:
        await message.answer("⚠️ Введи сумму числом, например `100`")
        return
    amount = Decimal(match.group(1).replace(",", "."))
    await state.update_data(debt_amount=str(amount))
    await state.set_state(DebtFSM.waiting_for_comment)
    await message.answer("Комментарий (или напиши `-` если без комментария):")


@router.message(DebtFSM.waiting_for_comment)
async def process_debt_comment(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    dtype = DebtType(data["debt_type"])
    person = data["person_name"]
    amount = Decimal(data["debt_amount"])
    comment = None if message.text.strip() == "-" else message.text.strip()
    await state.clear()

    async with async_session_maker() as session:
        debt = Debt(
            user_id=user_id,
            debt_type=dtype,
            person_name=person,
            amount=amount,
            remaining_amount=amount,
            comment=comment
        )
        session.add(debt)

        # Если я занял у кого-то на форс-мажор или дал из подушки
        if dtype == DebtType.OWES_ME:
            # Деньги ушли из подушки человеку
            env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.SAVINGS)
            s_env = (await session.execute(env_stmt)).scalar_one_or_none()
            if s_env:
                s_env.current_balance = max(s_env.current_balance - amount, Decimal("0.00"))

        await session.commit()

    arrow = "🔴 Я должен" if dtype == DebtType.I_OWE else "🟢 Мне должен"
    await message.answer(
        f"✅ Долг записан!\n\n"
        f"• {arrow}: **{person}**\n"
        f"• Сумма: **{amount} BYN**\n"
        + (f"• Комментарий: {comment}\n" if comment else "")
        + "\n💡 Долги автоматически учитываются при балансировке подушки.",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "debt_action:list")
async def cb_debts_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with async_session_maker() as session:
        stmt = select(Debt).where(Debt.user_id == user_id, Debt.is_closed == False)
        debts = (await session.execute(stmt)).scalars().all()

    if not debts:
        await callback.message.edit_text("🎉 У тебя нет активных долгов!", reply_markup=get_debts_menu_keyboard())
        await callback.answer()
        return

    lines = ["📋 **Активные долги:**\n"]
    for d in debts:
        icon = "🔴 Ты должен" if d.debt_type == DebtType.I_OWE else "🟢 Тебе должен"
        lines.append(f"{icon} **{d.person_name}**: {d.remaining_amount} BYN" + (f" ({d.comment})" if d.comment else ""))

    lines.append("\n_Чтобы закрыть долг, используй команду /closedebt <имя>_")
    await callback.message.edit_text("\n".join(lines), reply_markup=get_debts_menu_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.message(F.text.startswith("/closedebt"))
async def cmd_close_debt(message: types.Message):
    name = message.text.replace("/closedebt", "").strip().lower()
    if not name:
        await message.answer("Использование: `/closedebt <имя>`", parse_mode="Markdown")
        return
    user_id = message.from_user.id
    async with async_session_maker() as session:
        stmt = select(Debt).where(Debt.user_id == user_id, Debt.is_closed == False)
        debts = (await session.execute(stmt)).scalars().all()
        target = next((d for d in debts if name in d.person_name.lower()), None)
        if not target:
            await message.answer(f"⚠️ Активный долг с именем «{name}» не найден.")
            return

        target.is_closed = True
        target.closed_at = datetime.utcnow()

        # Если мне вернули долг -> возвращаем в подушку
        if target.debt_type == DebtType.OWES_ME:
            env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.SAVINGS)
            s_env = (await session.execute(env_stmt)).scalar_one_or_none()
            if s_env:
                s_env.current_balance += target.remaining_amount

        await session.commit()
        ret_msg = f"✅ Долг с **{target.person_name}** на сумму **{target.remaining_amount} BYN** успешно закрыт!"
        if target.debt_type == DebtType.OWES_ME:
            ret_msg += " Деньги возвращены в подушку."
    await message.answer(ret_msg, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# ФИЧА 6: Обязательства & Расходники (рассрочки, кредиты, вейп)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "features:obligations")
async def cb_obligations_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with async_session_maker() as session:
        stmt = select(Obligation).where(Obligation.user_id == user_id, Obligation.is_active == True)
        obls = (await session.execute(stmt)).scalars().all()

    total_monthly = sum(o.monthly_amount for o in obls)
    credits_sum = sum(o.monthly_amount for o in obls if o.obligation_type in [ObligationType.CREDIT, ObligationType.INSTALLMENT])
    subs_sum = sum(o.monthly_amount for o in obls if o.obligation_type == ObligationType.SUBSCRIPTION)
    consumables_sum = sum(o.monthly_amount for o in obls if o.obligation_type == ObligationType.CONSUMABLE)

    text = (
        "💳 **Обязательства и регулярные расходники:**\n\n"
        f"Всего замораживается в месяц: **{total_monthly} BYN**\n"
        f"• Кредиты и рассрочки: **{credits_sum} BYN/мес**\n"
        f"• Абонементы и подписки: **{subs_sum} BYN/мес**\n"
        f"• Расходники (вейп, быт. химия): **{consumables_sum} BYN/мес**\n\n"
        "💡 *Всё это замораживается при начислении зарплаты в отдельный конверт "
        "и НЕ отнимает ежедневный лимит Safe-to-Spend!*"
    )
    await callback.message.edit_text(text, reply_markup=get_obligations_menu_keyboard(), parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.in_(["oblg_action:add_credit", "oblg_action:add_sub", "oblg_action:add_consumable"]))
async def cb_add_obligation_start(callback: types.CallbackQuery, state: FSMContext):
    type_map = {
        "oblg_action:add_credit": (ObligationType.INSTALLMENT, "рассрочки / кредита (например, `Рассрочка iPhone`)"),
        "oblg_action:add_sub": (ObligationType.SUBSCRIPTION, "абонемента (например, `Зал Gym24` или `Яндекс Плюс`)"),
        "oblg_action:add_consumable": (ObligationType.CONSUMABLE, "расходников (например, `Вейп/жижа`, `Бытовая химия`)"),
    }
    oblg_type, desc = type_map[callback.data]
    await state.update_data(oblg_type=oblg_type.value)
    await state.set_state(ObligationFSM.waiting_for_title)
    await callback.message.answer(f"📝 Введи название {desc}:")
    await callback.answer()


@router.message(ObligationFSM.waiting_for_title)
async def process_obligation_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text.strip())
    await state.set_state(ObligationFSM.waiting_for_monthly_amount)
    await message.answer("Сколько это стоит в месяц? Введи сумму в BYN (например: `65`):")


@router.message(ObligationFSM.waiting_for_monthly_amount)
async def process_obligation_amount(message: types.Message, state: FSMContext):
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", message.text)
    if not match:
        await message.answer("⚠️ Введи сумму числом, например: `65`")
        return
    amt = Decimal(match.group(1).replace(",", "."))
    data = await state.get_data()
    oblg_type = ObligationType(data["oblg_type"])

    if oblg_type in [ObligationType.INSTALLMENT, ObligationType.CREDIT]:
        await state.update_data(monthly_amount=str(amt))
        await state.set_state(ObligationFSM.waiting_for_months_left)
        await message.answer("Сколько месяцев осталось платить? (например: `6`):")
        return

    # Для подписок и расходников месяцев нет
    user_id = message.from_user.id
    title = data["title"]
    await state.clear()

    async with async_session_maker() as session:
        ob = Obligation(
            user_id=user_id,
            obligation_type=oblg_type,
            title=title,
            monthly_amount=amt,
            is_active=True
        )
        session.add(ob)
        await session.commit()

    await message.answer(
        f"✅ Добавлено: **{title}** — **{amt} BYN/мес**.\n"
        "Сумма будет автоматически замораживаться при следующем внесении зарплаты и не тронет дневной лимит!",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown"
    )


@router.message(ObligationFSM.waiting_for_months_left)
async def process_obligation_months(message: types.Message, state: FSMContext):
    match = re.search(r"(\d+)", message.text)
    months = int(match.group(1)) if match else 12
    data = await state.get_data()
    amt = Decimal(data["monthly_amount"])
    title = data["title"]
    oblg_type = ObligationType(data["oblg_type"])
    user_id = message.from_user.id
    await state.clear()

    async with async_session_maker() as session:
        ob = Obligation(
            user_id=user_id,
            obligation_type=oblg_type,
            title=title,
            monthly_amount=amt,
            total_months=months,
            months_left=months,
            is_active=True
        )
        session.add(ob)
        await session.commit()

    await message.answer(
        f"✅ Рассрочка **{title}** добавлена!\n"
        f"Платеж: **{amt} BYN/мес**, осталось: **{months} мес.**\n"
        "Деньги будут защищены от случайных ежедневных трат.",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "oblg_action:list")
async def cb_obligations_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with async_session_maker() as session:
        stmt = select(Obligation).where(Obligation.user_id == user_id, Obligation.is_active == True)
        obls = (await session.execute(stmt)).scalars().all()

    if not obls:
        await callback.message.edit_text("ℹ️ У тебя пока нет активных обязательств.", reply_markup=get_obligations_menu_keyboard())
        await callback.answer()
        return

    lines = ["📋 **Твои ежемесячные обязательства:**\n"]
    for o in obls:
        tag = "📦 Расходник" if o.obligation_type == ObligationType.CONSUMABLE else "💳 Платёж"
        m_info = f" (осталось {o.months_left} мес.)" if o.months_left else ""
        lines.append(f"• {tag} **{o.title}**: {o.monthly_amount} BYN/мес{m_info}")

    lines.append("\n_Для отключения используй /delete_oblg <название>_")
    await callback.message.edit_text("\n".join(lines), reply_markup=get_obligations_menu_keyboard(), parse_mode="Markdown")
    await callback.answer()


# ---------------------------------------------------------------------------
# ФИЧА 1: Диаграмма расходов по категориям
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "features:categories_chart")
async def cb_categories_chart(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with async_session_maker() as session:
        tx_stmt = select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.type == TransactionType.EXPENSE
        )
        txs = (await session.execute(tx_stmt)).scalars().all()

        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        currency = user.currency if user else "BYN"

    if not txs:
        await callback.message.answer("ℹ️ За текущий период пока нет расходов для построения диаграммы.")
        await callback.answer()
        return

    cat_totals = {}
    for t in txs:
        # Автоматическая классификация, если в категории было что-то общее
        cat = t.category or "💡 Прочее"
        if cat in ["Расход из Mini App", "EXPENSE", "Расход"]:
            cat = classify_expense(f"{t.merchant or ''} {t.raw_input_text or ''}")
        cat_totals[cat] = cat_totals.get(cat, Decimal("0.00")) + t.amount

    chart_bytes = AnalyticsService.generate_expense_categories_chart(cat_totals, currency=currency)
    photo = BufferedInputFile(chart_bytes, filename="categories_breakdown.png")

    lines = ["📊 **Распределение расходов по категориям:**\n"]
    for c, amt in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"• {c}: **{amt} {currency}**")

    await callback.message.answer_photo(photo=photo, caption="\n".join(lines), parse_mode="Markdown")
    await callback.answer()


# ---------------------------------------------------------------------------
# ФИЧА 5: Предварительный расчет времени до цели в месяцах
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "features:goal_eta")
async def cb_goal_eta(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            await callback.message.answer("⚠️ Сначала внеси зарплату через 💼 «Внести доход».")
            await callback.answer()
            return

        goals_stmt = select(Goal).where(Goal.user_id == user_id)
        goals = (await session.execute(goals_stmt)).scalars().all()

    # Оценка ежемесячного взноса = net_base * (savings_target_percent / 100)
    monthly_savings = (user.current_cycle_net_base * (user.savings_target_percent / Decimal("100.00"))).quantize(Decimal("0.01"))
    if monthly_savings <= Decimal("0.00"):
        monthly_savings = Decimal("100.00")  # базовый ориентир

    if not goals:
        text = (
            "🎯 **Расчет срока накопления:**\n\n"
            f"Твой текущий темп отчислений в копилку: **{monthly_savings} {user.currency}/месяц**.\n\n"
            "У тебя пока нет созданных целей. Создай первую командой:\n"
            "`/goal <название> <сумма>` (например, `/goal Ноутбук 2500`)"
        )
        await callback.message.answer(text, parse_mode="Markdown")
        await callback.answer()
        return

    lines = ["🎯 **Прогноз достижения твоих финансовых целей:**\n"]
    for g in goals:
        res = estimate_goal_months(g.target_amount, g.current_amount, monthly_savings)
        lines.append(f"🏆 **{g.title}** ({g.current_amount}/{g.target_amount} {user.currency})")
        lines.append(f"   {res['formatted']}\n")

    lines.append(f"_Расчет основан на твоих отчислениях в копилку: {monthly_savings} {user.currency}/мес._")
    await callback.message.answer("\n".join(lines), parse_mode="Markdown")
    await callback.answer()


@router.message(F.text.startswith("/goal"))
async def cmd_create_goal(message: types.Message):
    parts = message.text.replace("/goal", "").strip().rsplit(" ", 1)
    if len(parts) < 2:
        await message.answer("Использование: `/goal <название> <сумма>`\nПример: `/goal Ноутбук 2500`", parse_mode="Markdown")
        return
    title, amt_str = parts[0].strip(), parts[1].strip()
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", amt_str)
    if not match:
        await message.answer("⚠️ Укажи корректную сумму цели.")
        return
    target_amt = Decimal(match.group(1).replace(",", "."))
    user_id = message.from_user.id

    async with async_session_maker() as session:
        goal = Goal(
            user_id=user_id,
            title=title,
            target_amount=target_amt,
            current_amount=Decimal("0.00"),
            is_primary=True
        )
        session.add(goal)
        await session.commit()

    await message.answer(
        f"🎯 Цель **«{title}»** на сумму **{target_amt} BYN** успешно создана!\n"
        "Срок накопления доступен в разделе 🌟 «Функции» -> «Срок до цели».",
        parse_mode="Markdown"
    )


# ---------------------------------------------------------------------------
# ФИЧА 7: Рандомайзер (Купить или не покупать?)
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "features:randomizer")
async def cb_randomizer_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(RandomizerFSM.waiting_for_item)
    await callback.message.answer(
        "🎲 **Рандомайзер покупок «Брать или нет?»**\n\n"
        "Сомневаешься, стоит ли тратить деньги?\n"
        "Напиши, что именно ты хочешь купить (например: `вторая пара кроссовок`, `роллы на ужин`):"
    )
    await callback.answer()


@router.message(RandomizerFSM.waiting_for_item)
async def process_randomizer_input(message: types.Message, state: FSMContext):
    item = message.text.strip()
    await state.clear()
    verdict = decide_randomizer(item)

    text = (
        f"{verdict['emoji']} **Вердикт:** {verdict['decision']}\n\n"
        f"По поводу: **«{verdict['item']}»**\n\n"
        f"💬 _{verdict['reason']}_\n\n"
        f"🎲 _Испытай удачу снова в любой момент через «🌟 Функции»!_"
    )
    await message.answer(text, reply_markup=get_main_reply_keyboard(), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# ФИЧА 4: Напоминания о покупках в заданное время по МСК
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "features:shopping_list")
async def cb_shopping_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(ShoppingReminderFSM.waiting_for_items)
    await callback.message.answer(
        "⏰ **Напоминание о покупках в магазине**\n\n"
        "Напиши список покупок (например: `молоко, яйца, хлеб, стики, курица`):"
    )
    await callback.answer()


@router.message(ShoppingReminderFSM.waiting_for_items)
async def process_shopping_items(message: types.Message, state: FSMContext):
    await state.update_data(items=message.text.strip())
    await state.set_state(ShoppingReminderFSM.waiting_for_time)
    await message.answer(
        "Во сколько напомнить по **московскому времени (МСК)**?\n"
        "Введи время в формате `ЧЧ:ММ` (например: `18:30` или `19:00`):"
    )


@router.message(ShoppingReminderFSM.waiting_for_time)
async def process_shopping_time(message: types.Message, state: FSMContext):
    match = re.search(r"(\d{1,2})[:.-](\d{2})", message.text.strip())
    if not match:
        await message.answer("⚠️ Введи время в формате `18:30` или `19:00` по МСК:")
        return

    hours, mins = int(match.group(1)), int(match.group(2))
    if not (0 <= hours <= 23 and 0 <= mins <= 59):
        await message.answer("⚠️ Некорректное время. Часы 0-23, минуты 0-59.")
        return

    data = await state.get_data()
    items = data["items"]
    user_id = message.from_user.id
    await state.clear()

    now_msk = datetime.now(MSK_TZ)
    target_dt = now_msk.replace(hour=hours, minute=mins, second=0, microsecond=0)
    if target_dt <= now_msk:
        # Если время уже прошло сегодня — ставим на завтра
        from datetime import timedelta
        target_dt += timedelta(days=1)

    async with async_session_maker() as session:
        rem = ShoppingReminder(
            user_id=user_id,
            items_text=items,
            remind_at=target_dt,
            is_sent=False
        )
        session.add(rem)
        await session.commit()

    time_str = target_dt.strftime("%H:%M")
    date_str = target_dt.strftime("%d.%m")
    await message.answer(
        f"✅ Напоминание установлено!\n\n"
        f"🛒 **Список:** {items}\n"
        f"⏰ **Время:** {time_str} МСК ({date_str})\n\n"
        "Я пришлю тебе сообщение точно в этот момент!",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown"
    )
