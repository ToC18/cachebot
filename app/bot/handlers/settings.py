from datetime import datetime
from decimal import Decimal
from aiogram import Router, types, F
from aiogram.fsm.context import FSMContext
from sqlalchemy import select
from app.database.session import async_session_maker
from app.database.models import User
from app.bot.keyboards import (
    get_settings_keyboard, 
    get_savings_percent_keyboard, 
    get_payday_selection_keyboard,
    get_main_reply_keyboard,
    get_open_mini_app_keyboard,
    MINI_APP_BUTTON_TEXT,
)
from app.bot.states import SettingsFSM
from app.config import settings

router = Router(name="settings_router")


@router.message(F.text == MINI_APP_BUTTON_TEXT)
async def btn_open_mini_app(message: types.Message):
    if not settings.webapp_url.startswith("https://"):
        await message.answer("⚠️ Приложение сейчас недоступно, попробуй чуть позже.")
        return
    await message.answer(
        "📱 Твоё личное приложение с бюджетом:",
        reply_markup=get_open_mini_app_keyboard()
    )


@router.message(F.text == "📱 Mini App (Инфо)")
async def btn_miniapp_info(message: types.Message):
    user_id = message.from_user.id
    local_url = f"http://localhost:8000/app?user_id={user_id}"

    text = (
        "📱 **Telegram Mini App (TMA)**\n\n"
        "Интерфейс мобильного веб-приложения полностью готов и встроен в сервер!\n\n"
        f"🌐 **Локально в браузере (на ПК/телефоне в одной сети):**\n"
        f"`{local_url}`\n\n"
        "🔒 **Чтобы открывать окно прямо внутри Telegram на iPhone/Android:**\n"
        "Telegram требует защищенную ссылку `https://`.\n"
        "При запуске через `start_all.py` туннель поднимается автоматически!"
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(F.text == "⚙️ Настройки")
async def btn_settings(message: types.Message):
    user_id = message.from_user.id
    async with async_session_maker() as session:
        stmt = select(User).where(User.id == user_id)
        user = (await session.execute(stmt)).scalar_one_or_none()

    if not user:
        await message.answer(
            "⚠️ Твой профиль еще не создан. Нажми 💼 «Внести доход», чтобы начать!",
            reply_markup=get_main_reply_keyboard()
        )
        return

    date_suffix = ""
    if user.next_payday_date:
        date_suffix = f" (или до {user.next_payday_date.strftime('%d.%m.%Y')})"

    paywall_status = "Включен ✅" if user.show_hourly_rate else "Отключен ❌"

    text = (
        "⚙️ **Параметры твоего финансового профиля:**\n\n"
        f"📅 День следующей зарплаты: **{user.payday_day_of_month}-е число**{date_suffix}\n"
        f"🎯 Доля накоплений («Заплати себе»): **{user.savings_target_percent}%**\n"
        f"🚌 Тариф дороги туда-обратно: **{user.roundtrip_commute_fare} BYN** ({user.work_shifts_per_month} смен)\n"
        f"⏳ Расчет часов работы (Paywall): **{paywall_status}**\n\n"
        "Нажми на кнопку ниже, чтобы изменить нужный параметр:"
    )

    await message.answer(
        text,
        reply_markup=get_settings_keyboard(
            payday_day=user.payday_day_of_month,
            savings_percent=user.savings_target_percent,
            commute_fare=user.roundtrip_commute_fare,
            shifts=user.work_shifts_per_month,
            show_hourly_rate=user.show_hourly_rate
        ),
        parse_mode="Markdown"
    )


@router.callback_query(F.data == "settings:toggle_paywall")
async def handle_toggle_paywall(callback: types.CallbackQuery):
    """Фича 3: включение / отключение показа часов работы."""
    user_id = callback.from_user.id
    async with async_session_maker() as session:
        stmt = select(User).where(User.id == user_id)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user:
            user.show_hourly_rate = not user.show_hourly_rate
            await session.commit()
            new_state = user.show_hourly_rate
            payday_day = user.payday_day_of_month
            savings_pct = user.savings_target_percent
            commute_fare = user.roundtrip_commute_fare
            shifts = user.work_shifts_per_month
        else:
            return

    status_str = "включен ✅" if new_state else "отключен ❌"
    await callback.answer(f"Калькулятор часов жизни: {status_str}")

    await callback.message.edit_reply_markup(
        reply_markup=get_settings_keyboard(
            payday_day=payday_day,
            savings_percent=savings_pct,
            commute_fare=commute_fare,
            shifts=shifts,
            show_hourly_rate=new_state
        )
    )


@router.callback_query(F.data == "settings:savings")
async def handle_settings_savings(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "🎯 **Выбери процент дохода, который автоматически уходит в копилку (Pay Yourself First):**\n\n"
        "• 10% — мягкий старт\n"
        "• 20% — рекомендуемый баланс\n"
        "• 30% — ускоренное накопление подушки",
        reply_markup=get_savings_percent_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_savings:"))
async def handle_set_savings_value(callback: types.CallbackQuery):
    percent = Decimal(callback.data.split(":")[1])
    user_id = callback.from_user.id

    async with async_session_maker() as session:
        stmt = select(User).where(User.id == user_id)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user:
            user.savings_target_percent = percent
            await session.commit()

    await callback.message.edit_text(
        f"✅ Процент в копилку изменен на **{percent}%**.\n"
        f"Он применится при следующем внесении дохода!",
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "settings:payday")
async def handle_settings_payday(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📅 **Выбери постоянный день зарплаты:**",
        reply_markup=get_payday_selection_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data == "settings:back")
async def handle_settings_back(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    async with async_session_maker() as session:
        stmt = select(User).where(User.id == user_id)
        user = (await session.execute(stmt)).scalar_one_or_none()

    if not user:
        return

    await callback.message.edit_text(
        "⚙️ **Параметры твоего финансового профиля:**",
        reply_markup=get_settings_keyboard(
            payday_day=user.payday_day_of_month,
            savings_percent=user.savings_target_percent,
            commute_fare=user.roundtrip_commute_fare,
            shifts=user.work_shifts_per_month,
            show_hourly_rate=user.show_hourly_rate
        ),
        parse_mode="Markdown"
    )
    await callback.answer()
