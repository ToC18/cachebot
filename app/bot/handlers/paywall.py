import re
from decimal import Decimal
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from app.database.session import async_session_maker
from app.database.models import User
from app.services.finance_engine import FinanceEngine
from app.bot.states import PaywallFSM
from app.bot.keyboards import get_main_reply_keyboard

router = Router(name="paywall_router")


@router.message(F.text == "⏳ Умный Paywall")
async def btn_paywall_start(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    async with async_session_maker() as session:
        stmt = select(User).where(User.id == user_id)
        user = (await session.execute(stmt)).scalar_one_or_none()

    if user and not user.show_hourly_rate:
        await message.answer(
            "⏳ **Умный Paywall отключен** в твоих настройках.\n"
            "Включить его обратно можно в разделе ⚙️ «Настройки».",
            reply_markup=get_main_reply_keyboard(),
            parse_mode="Markdown"
        )
        return

    await state.set_state(PaywallFSM.waiting_for_item_or_price)
    await message.answer(
        "⏳ **Умный Paywall (калькулятор времени жизни)**\n\n"
        "Напиши стоимость покупки или фразу, например:\n"
        "• `350`\n"
        "• `кроссовки 350`\n"
        "• `билет 45`",
        reply_markup=get_main_reply_keyboard(),
        parse_mode="Markdown"
    )


@router.message(PaywallFSM.waiting_for_item_or_price)
async def process_paywall_fsm_input(message: types.Message, state: FSMContext):
    text = message.text.strip()
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", text)
    if not match:
        await message.answer("⚠️ Введи сумму числом, например: `350` или `наушники 200`")
        return

    price = Decimal(match.group(1).replace(",", "."))
    item_name = text.replace(match.group(1), "").strip() or None

    await state.clear()
    await _process_paywall(message, price, item_name)


@router.message(F.text.startswith("?"))
async def handle_question_paywall(message: types.Message):
    """Handles: '? 350' or '? кроссовки 350'"""
    text = message.text[1:].strip()
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", text)
    if not match:
        await message.answer("ℹ️ Формат команды: `? 350` или `? наушники 200`", parse_mode="Markdown")
        return

    price = Decimal(match.group(1).replace(",", "."))
    item_name = text.replace(match.group(1), "").strip() or None

    await _process_paywall(message, price, item_name)


@router.message(F.text.lower().startswith("купить"))
async def handle_buy_paywall(message: types.Message):
    """Handles: 'купить кроссовки 350' or 'купить 350'"""
    text = message.text[6:].strip()
    match = re.search(r"(\d+(?:[.,]\d{1,2})?)", text)
    if not match:
        await message.answer("ℹ️ Формат команды: `купить кроссовки 350`", parse_mode="Markdown")
        return

    price = Decimal(match.group(1).replace(",", "."))
    item_name = text.replace(match.group(1), "").strip() or None

    await _process_paywall(message, price, item_name)


async def _process_paywall(message: types.Message, price: Decimal, item_name: str = None):
    user_id = message.from_user.id
    async with async_session_maker() as session:
        stmt = select(User).where(User.id == user_id)
        res = await session.execute(stmt)
        user = res.scalar_one_or_none()

    if user and not user.show_hourly_rate:
        await message.answer(
            f"💰 Стоимость покупки: **{price} {user.currency}**\n"
            "(Расчет часов жизни скрыт по твоей настройке)",
            parse_mode="Markdown"
        )
        return

    if not user or user.current_hourly_rate <= Decimal("0.00"):
        await message.answer(
            "⚠️ Твоя часовая ставка еще не рассчитана!\n"
            "Сначала внеси доход через кнопку 💼 «Внести доход».",
            parse_mode="Markdown"
        )
        return

    result = FinanceEngine.calculate_work_hours_paywall(
        price=price, 
        hourly_rate=user.current_hourly_rate, 
        item_name=item_name
    )
    await message.answer(result["formatted_message"], parse_mode="Markdown")
