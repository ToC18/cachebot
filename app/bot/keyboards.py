from decimal import Decimal
from aiogram.types import (
    InlineKeyboardMarkup, 
    InlineKeyboardButton, 
    ReplyKeyboardMarkup, 
    KeyboardButton,
    WebAppInfo
)
from app.config import settings

MINI_APP_BUTTON_TEXT = "📱 Открыть Mini App"
MORE_FEATURES_BUTTON_TEXT = "🌟 Функции"


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Главная постоянная навигационная клавиатура бота."""
    rows = []

    if settings.webapp_url.startswith("https://"):
        rows.append([KeyboardButton(text=MINI_APP_BUTTON_TEXT, web_app=WebAppInfo(url=settings.webapp_url))])

    rows.extend([
        [
            KeyboardButton(text="💼 Внести доход"),
            KeyboardButton(text="📊 Мой бюджет")
        ],
        [
            KeyboardButton(text="⏳ Умный Paywall"),
            KeyboardButton(text="⚙️ Настройки")
        ],
        [
            KeyboardButton(text=MORE_FEATURES_BUTTON_TEXT)
        ]
    ])

    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True
    )


def get_open_mini_app_keyboard() -> InlineKeyboardMarkup:
    """Инлайн-кнопка открытия Mini App (передаёт initData)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="📱 Открыть приложение",
                web_app=WebAppInfo(url=settings.webapp_url)
            )
        ]]
    )


def get_more_features_keyboard() -> InlineKeyboardMarkup:
    """Меню дополнительных функций бота (фичи 1, 2, 4, 5, 6, 7, 8)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎯 Подушка & Долги", callback_data="features:debts"),
                InlineKeyboardButton(text="💳 Обязательства & Вейп", callback_data="features:obligations"),
            ],
            [
                InlineKeyboardButton(text="📈 Диаграмма трат", callback_data="features:categories_chart"),
                InlineKeyboardButton(text="🎯 Срок до цели", callback_data="features:goal_eta"),
            ],
            [
                InlineKeyboardButton(text="🎲 Брать или нет?", callback_data="features:randomizer"),
                InlineKeyboardButton(text="⏰ Список покупок", callback_data="features:shopping_list"),
            ],
        ]
    )


def get_debts_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="💸 Взять из подушки", callback_data="debt_action:emergency_withdraw"),
            ],
            [
                InlineKeyboardButton(text="🔴 Я должен (записать)", callback_data="debt_action:add_i_owe"),
                InlineKeyboardButton(text="🟢 Мне должны (записать)", callback_data="debt_action:add_owes_me"),
            ],
            [
                InlineKeyboardButton(text="📋 Список долгов", callback_data="debt_action:list"),
                InlineKeyboardButton(text="🔙 Назад", callback_data="features:back_main"),
            ],
        ]
    )


def get_obligations_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Рассрочка / Кредит", callback_data="oblg_action:add_credit"),
                InlineKeyboardButton(text="➕ Абонемент", callback_data="oblg_action:add_sub"),
            ],
            [
                InlineKeyboardButton(text="➕ Расходники (вейп/химия)", callback_data="oblg_action:add_consumable"),
            ],
            [
                InlineKeyboardButton(text="📋 Мои обязательства", callback_data="oblg_action:list"),
                InlineKeyboardButton(text="🔙 Назад", callback_data="features:back_main"),
            ],
        ]
    )


def get_income_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💼 Полная зарплата (новый цикл)", 
                    callback_data="income_type:full_salary"
                )
            ],
            [
                InlineKeyboardButton(
                    text="💸 Аванс / Часть зарплаты", 
                    callback_data="income_type:advance"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🎁 Премия / Подработка", 
                    callback_data="income_type:bonus"
                )
            ],
            [
                InlineKeyboardButton(text="Отмена", callback_data="income_cancel")
            ]
        ]
    )


def get_payday_selection_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="10-е число", callback_data="payday_day:10"),
                InlineKeyboardButton(text="15-е число", callback_data="payday_day:15"),
                InlineKeyboardButton(text="20-е число", callback_data="payday_day:20")
            ],
            [
                InlineKeyboardButton(text="25-е число", callback_data="payday_day:25"),
                InlineKeyboardButton(text="Конец месяца (30/31)", callback_data="payday_day:30")
            ],
            [
                InlineKeyboardButton(
                    text="📅 Ввести точную дату вручную (ДД.ММ)", 
                    callback_data="payday_day:custom"
                )
            ],
            [
                InlineKeyboardButton(text="⏩ Оставить как есть", callback_data="payday_day:skip")
            ]
        ]
    )


def get_settings_keyboard(
    payday_day: int,
    savings_percent: Decimal,
    commute_fare: Decimal,
    shifts: int,
    show_hourly_rate: bool = True
) -> InlineKeyboardMarkup:
    paywall_toggle_text = "⏳ Часы работы: ВКЛ ✅" if show_hourly_rate else "⏳ Часы работы: ВЫКЛ ❌"

    rows = [
        [
            InlineKeyboardButton(
                text=f"📅 День зарплаты: {payday_day}-е", 
                callback_data="settings:payday"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🎯 Копилка: {savings_percent}%", 
                callback_data="settings:savings"
            )
        ],
        [
            InlineKeyboardButton(
                text=f"🚌 Проезд ({shifts} смен по {commute_fare} BYN)", 
                callback_data="settings:commute"
            )
        ],
        [
            InlineKeyboardButton(
                text=paywall_toggle_text,
                callback_data="settings:toggle_paywall"
            )
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_savings_percent_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="10%", callback_data="set_savings:10"),
                InlineKeyboardButton(text="15%", callback_data="set_savings:15"),
                InlineKeyboardButton(text="20% (Стандарт)", callback_data="set_savings:20")
            ],
            [
                InlineKeyboardButton(text="25%", callback_data="set_savings:25"),
                InlineKeyboardButton(text="30% (FIRE)", callback_data="set_savings:30")
            ],
            [
                InlineKeyboardButton(text="🔙 Назад", callback_data="settings:back")
            ]
        ]
    )


def get_crisis_keyboard(overspent: Decimal) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📉 Снизить лимит на эту неделю", 
                    callback_data=f"crisis:dampen:{overspent}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🍕 Покрыть из фонда выходных", 
                    callback_data=f"crisis:weekend:{overspent}"
                )
            ]
        ]
    )


def get_evening_surplus_keyboard(savings: Decimal) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🎯 Да, в копилку (+{savings} BYN)", 
                    callback_data=f"surplus:goal:{savings}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🍕 В фонд выходных", 
                    callback_data=f"surplus:weekend:{savings}"
                ),
                InlineKeyboardButton(
                    text="Оставить на завтра", 
                    callback_data="surplus:dismiss"
                )
            ]
        ]
    )
