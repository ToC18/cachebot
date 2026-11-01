"""Smart assistant engine:
- Categorization of expenses
- Randomizer "Купить / Не покупать"
- Goal time estimation
- Calorie deficit & weight loss calculator (Mifflin-St Jeor formula)
- Smart AI recipe generator based on exact ingredients and staples
- Nutrition database & text-to-calorie parser
"""
from decimal import Decimal
import random
import re
from typing import Dict, List, Tuple, Optional


EXPENSE_CATEGORIES = [
    "🛒 Продукты / Супермаркеты",
    "☕ Кафе и Рестораны",
    "🚕 Транспорт и Бензин",
    "💊 Здоровье и Аптека",
    "🏠 Счета и ЖКХ",
    "📱 Связь и Подписки",
    "👕 Одежда и Обувь",
    "🎉 Развлечения и Отдых",
    "📦 Маркетплейсы / Покупки",
    "💡 Прочее",
]


CATEGORY_KEYWORDS: List[Tuple[str, List[str]]] = [
    ("🛒 Продукты / Супермаркеты", [
        "евроопт", "соседи", "копеечка", "санта", "гиппо", "green", "гриин", "корона",
        "хлеб", "молоко", "сыр", "колбас", "мясо", "яйц", "масло", "овощ", "фрукт",
        "яблок", "банан", "куриц", "круп", "рис", "гречк", "макарон", "шоколад", "вода",
        "магазин", "универсам", "супермаркет", "продукты", "fix price", "фикс прайс"
    ]),
    ("☕ Кафе и Рестораны", [
        "кофе", "капучино", "латте", "эспрессо", "мак", "кфс", "kfc", "бургер", "додо",
        "пицца", "суши", "роллы", "шаурма", "донер", "обед", "ужин", "бистро", "ресторан",
        "кафе", "бар", "пиво", "булочн", "пекарн", "десерт"
    ]),
    ("🚕 Транспорт и Бензин", [
        "яндекс go", "яндекс такси", "такси", "uber", "бензин", "азс", "лукойл", "белоруснефть",
        "газпромнефть", "маршрутк", "электричк", "поезд", "метро", "автобус", "троллейбус",
        "проездной", "талон", "парковк", "мойка", "сто", "autostan", "минсктранс"
    ]),
    ("💊 Здоровье и Аптека", [
        "аптека", "лекарств", "таблетк", "витамин", "пластыр", "врач", "клиник", "анализ",
        "стоматолог", "зуб", "оптика", "линз"
    ]),
    ("🏠 Счета и ЖКХ", [
        "квартплат", "жкх", "аренд", "электричеств", "свет", "газ", "отоплен", "интернет",
        "байфлай", "а1", "мтс", "life", "ерип"
    ]),
    ("📱 Связь и Подписки", [
        "подписк", "яндекс плюс", "apple", "google", "spotify", "vk", "телеграм прем",
        "telegram premium", "ютуб", "youtube", "айфон"
    ]),
    ("👕 Одежда и Обувь", [
        "одежд", "обув", "куртк", "кроссовк", "джинс", "футболк", "носки", "штаны",
        "zara", "bershka", "mango", "секонд", "вайлдберриз", "wb", "wildberries"
    ]),
    ("🎉 Развлечения и Отдых", [
        "кино", "билет", "боулинг", "квест", "концерт", "театр", "игра", "steam",
        "playstation", "кальян", "клуб"
    ]),
    ("📦 Маркетплейсы / Покупки", [
        "ozon", "озон", "aliexpress", "али", "wildberries", "wb", "посылк", "доставк",
        "электроник", "наушник", "чехол", "вейп", "жиж", "испарител", "стики", "iqos"
    ]),
]


def classify_expense(text: str) -> str:
    lowered = text.lower()
    for cat_name, keywords in CATEGORY_KEYWORDS:
        if any(kw in lowered for kw in keywords):
            return cat_name
    return "💡 Прочее"


# ---------------------------------------------------------------------------
# Рандомайзер
# ---------------------------------------------------------------------------

BUY_REASONS = [
    "Жизнь одна, а эта вещь реально сделает твой день лучше и добавит энергии.",
    "Если ты думаешь об этом уже не первый день — бери, иначе всё равно потом вернёшься.",
    "Инвестиция в собственный комфорт окупается хорошим настроением и продуктивностью.",
    "Бюджет позволяет, а маленькие радости спасают от выгорания. Одобряю!",
    "Бери! Главное — не винить себя после покупки, а искренне кайфануть от приобретения.",
    "Это решит конкретную задачу и сэкономит тебе кучу времени или нервов.",
    "Зелёный свет! В конце концов, деньги — это инструмент для радости, а не просто цифры на экране.",
    "Если это качественная вещь, которая прослужит долго — покупка на 100% оправдана.",
    "Бери, но с одним условием: сегодня больше ни на какие спонтанные мелочи не тратимся 😉",
]

DONT_BUY_REASONS = [
    "Стоп-кран! Через 48 часов этот импульс пройдёт, а деньги останутся в кармане.",
    "Положи в корзину и подожди до завтра. Если утром желание не пропадёт — вернёшься.",
    "Это типичный дофаминовый крючок: радости будет на 15 минут, а дыра в Safe-to-Spend — на неделю.",
    "Твоя финансовая подушка прямо сейчас смотрит на тебя с лёгким укором. Отложи покупку.",
    "Лучше закинь эту сумму прямо сейчас в цель — приближение к мечте даёт в 10 раз больше кайфа.",
    "Спроси себя честно: тебе нужна сама вещь или просто хочется снять стресс покупкой?",
    "Не сегодня. Потратить легко, а зарабатывать на это придётся своими реальными часами жизни.",
    "Красный сигнал светофора! Пусть эти деньги поработают на твою финансовую свободу.",
    "Эмоциональная покупка detected. Закрой вкладку и выпей стакан воды — проверенный антидот.",
]


def decide_randomizer(item_name: str = None) -> Dict[str, str]:
    should_buy = random.choice([True, False])
    return {
        "decision": "КУПИТЬ ✅" if should_buy else "НЕ ПОКУПАТЬ 🛑",
        "reason": random.choice(BUY_REASONS if should_buy else DONT_BUY_REASONS),
        "emoji": "🟢" if should_buy else "🔴",
        "item": item_name or "эта вещь"
    }


def estimate_goal_months(target_amount: Decimal, current_amount: Decimal, monthly_contribution: Decimal) -> Dict[str, any]:
    remaining = max(target_amount - current_amount, Decimal("0.00"))
    if remaining <= Decimal("0.00"):
        return {"months": 0, "remaining": Decimal("0.00"), "formatted": "Цель уже достигнута! 🎉"}

    if monthly_contribution <= Decimal("0.00"):
        return {"months": None, "remaining": remaining, "formatted": "При текущем темпе цель не будет достигнута. Увеличь % в копилку!"}

    months = float(remaining / monthly_contribution)
    months_rounded = max(1, round(months, 1))

    whole = int(months_rounded)
    if whole % 10 == 1 and whole % 100 != 11:
        m_word = "месяц"
    elif 2 <= whole % 10 <= 4 and not (12 <= whole % 100 <= 14):
        m_word = "месяца"
    else:
        m_word = "месяцев"

    return {
        "months": months_rounded,
        "remaining": remaining,
        "formatted": f"Осталось: **{remaining} BYN** — при текущем темпе это займет **~{months_rounded} {m_word}**."
    }


# ---------------------------------------------------------------------------
# ЗОЖ: Расчет калорий и дефицита для похудения (Формула Миффлина-Сан Жеора)
# ---------------------------------------------------------------------------

ACTIVITY_FACTORS = {
    "sedentary": 1.2,      # сидячий образ жизни (офис, минимум шагов)
    "light": 1.375,        # 1-3 тренировки в неделю или 8-10к шагов
    "moderate": 1.55,      # 3-5 тренировок в неделю
    "high": 1.725          # тяжелая физ. работа или ежедневный спорт
}


def calculate_weight_loss_plan(
    current_weight: float,
    target_weight: float,
    height_cm: int = 175,
    age: int = 25,
    gender: str = "male",
    activity_level: str = "moderate"
) -> Dict[str, any]:
    """Рассчитывает суточную норму калорий, дефицит и реальный срок похудения к цели."""
    # Базовый обмен веществ (BMR) по Миффлину-Сан Жеору
    if gender == "female":
        bmr = 10 * current_weight + 6.25 * height_cm - 5 * age - 161
    else:
        bmr = 10 * current_weight + 6.25 * height_cm - 5 * age + 5

    factor = ACTIVITY_FACTORS.get(activity_level, 1.375)
    tdee = bmr * factor  # Поддержка текущего веса

    weight_diff = current_weight - target_weight

    if weight_diff <= 0:
        return {
            "bmr": round(bmr),
            "maintenance_calories": round(tdee),
            "target_calories": round(tdee),
            "deficit": 0,
            "weeks_to_goal": 0,
            "bzu": {"proteins": round(current_weight * 1.6), "fats": round(current_weight * 0.9), "carbs": round((tdee - current_weight * 1.6 * 4 - current_weight * 0.9 * 9) / 4)},
            "summary": "Твой вес уже в норме или ниже цели! Рекомендуется режим поддержания."
        }

    # Безопасный дефицит 15-20% (~400-500 ккал) для сброса 0.5 - 0.7 кг жира в неделю
    # 1 кг жира = ~7700 ккал
    deficit = min(500, max(300, round(tdee * 0.20)))
    target_calories = max(1200 if gender == "female" else 1500, round(tdee - deficit))

    # Срок похудения в неделях и месяцах
    weekly_fat_loss = (deficit * 7) / 7700.0  # кг в неделю
    weeks_to_goal = max(1, round(weight_diff / weekly_fat_loss, 1))
    months_to_goal = max(0.5, round(weeks_to_goal / 4.3, 1))

    # БЖУ на дефиците: Белки 1.8-2.0г/кг (защита мышц), Жиры 0.8-1.0г/кг, остаток Углеводы
    proteins = round(current_weight * 1.8)
    fats = round(current_weight * 0.8)
    carbs = max(50, round((target_calories - (proteins * 4) - (fats * 9)) / 4))

    return {
        "bmr": round(bmr),
        "maintenance_calories": round(tdee),
        "target_calories": target_calories,
        "deficit": round(tdee - target_calories),
        "weight_to_lose": round(weight_diff, 1),
        "weeks_to_goal": weeks_to_goal,
        "months_to_goal": months_to_goal,
        "bzu": {"proteins": proteins, "fats": fats, "carbs": carbs},
        "summary": f"Чтобы сбросить **{round(weight_diff, 1)} кг** до цели ({target_weight} кг), тебе нужно есть **{target_calories} ккал/день** (дефицит ~{round(tdee - target_calories)} ккал). При таком темпе цель будет достигнута через **~{months_to_goal} мес.** ({int(weeks_to_goal)} нед.)."
    }


# ---------------------------------------------------------------------------
# База калорийности и парсер еды
# ---------------------------------------------------------------------------

FOOD_DATABASE: Dict[str, Dict[str, float]] = {
    "яйцо": {"cal": 75, "p": 6.5, "f": 5.0, "c": 0.5, "unit": "1 шт"},
    "яйца": {"cal": 150, "p": 13.0, "f": 10.0, "c": 1.0, "unit": "2 шт"},
    "куриное филе": {"cal": 165, "p": 31.0, "f": 3.6, "c": 0.0, "unit": "100г"},
    "курица": {"cal": 190, "p": 27.0, "f": 8.0, "c": 0.0, "unit": "100г"},
    "грудка": {"cal": 165, "p": 31.0, "f": 3.6, "c": 0.0, "unit": "100г"},
    "говядина": {"cal": 220, "p": 26.0, "f": 12.0, "c": 0.0, "unit": "100г"},
    "гречка": {"cal": 130, "p": 4.5, "f": 1.3, "c": 25.0, "unit": "100г вареной"},
    "рис": {"cal": 130, "p": 2.7, "f": 0.3, "c": 28.0, "unit": "100г вареного"},
    "овсянка": {"cal": 170, "p": 6.0, "f": 3.5, "c": 28.0, "unit": "порция (50г сухой)"},
    "макароны": {"cal": 160, "p": 5.5, "f": 0.9, "c": 31.0, "unit": "100г вареных"},
    "творог": {"cal": 120, "p": 18.0, "f": 5.0, "c": 3.0, "unit": "100г"},
    "тунец": {"cal": 105, "p": 24.0, "f": 1.0, "c": 0.0, "unit": "100г в с/с"},
    "сыр": {"cal": 105, "p": 7.5, "f": 8.5, "c": 0.5, "unit": "30г (кусочек)"},
    "хлеб": {"cal": 80, "p": 2.5, "f": 1.0, "c": 15.0, "unit": "1 кусок (30г)"},
    "банан": {"cal": 95, "p": 1.3, "f": 0.3, "c": 23.0, "unit": "1 шт"},
    "яблоко": {"cal": 70, "p": 0.5, "f": 0.3, "c": 16.0, "unit": "1 шт"},
    "протеин": {"cal": 120, "p": 24.0, "f": 1.5, "c": 3.0, "unit": "1 порция"},
    "шаурма": {"cal": 650, "p": 32.0, "f": 28.0, "c": 65.0, "unit": "стандартная"},
    "пицца": {"cal": 280, "p": 11.0, "f": 10.0, "c": 34.0, "unit": "1 кусок"},
    "бургер": {"cal": 520, "p": 24.0, "f": 26.0, "c": 45.0, "unit": "1 шт"},
    "кофе с молоком": {"cal": 90, "p": 4.0, "f": 3.5, "c": 8.0, "unit": "капучино 250мл"},
    "шоколад": {"cal": 270, "p": 3.0, "f": 16.0, "c": 28.0, "unit": "полплитки (50г)"},
    "салат": {"cal": 80, "p": 1.5, "f": 4.5, "c": 6.0, "unit": "порция огурцы/помидоры"},
}


def parse_food_input(text: str) -> Dict[str, any]:
    """Распознает продукт, блюдо или штрихкод из текста и рассчитывает КБЖУ."""
    lowered = text.lower().strip()
    
    # 1. Если введен штрихкод (например 481013000...)
    if re.fullmatch(r"\d{8,14}", lowered):
        # Базовые популярные штрихкоды РБ/РФ для примера
        barcode_mock = {
            "481013": {"name": "Творог Савушкин 5%", "cal": 120, "p": 16, "f": 5, "c": 3},
            "481026": {"name": "Молоко Брест-Литовск 2.5%", "cal": 53, "p": 2.8, "f": 2.5, "c": 4.7},
            "460060": {"name": "Овсяные хлопья Ясно Солнышко", "cal": 360, "p": 12, "f": 6, "c": 62},
        }
        for prefix, item in barcode_mock.items():
            if lowered.startswith(prefix):
                return {"food_name": item["name"], "calories": item["cal"], "proteins": item["p"], "fats": item["f"], "carbs": item["c"], "matched": True}
        return {"food_name": f"Товар по штрихкоду #{lowered}", "calories": 180, "proteins": 8, "fats": 5, "carbs": 24, "matched": True}

    # 2. Если указано число калорий напрямую (например, "обед 600" или "600 ккал")
    match_num = re.search(r"(\d+)\s*(?:ккал|кал)?", lowered)
    has_only_number = match_num and len(lowered.replace(match_num.group(1), "").strip()) < 3
    if has_only_number:
        cal = float(match_num.group(1))
        return {"food_name": "Прием пищи", "calories": cal, "proteins": round(cal * 0.25 / 4), "fats": round(cal * 0.25 / 9), "carbs": round(cal * 0.5 / 4), "matched": True}

    # 3. Поиск по базе продуктов
    total_cal = 0
    total_p = 0
    total_f = 0
    total_c = 0
    found_items = []

    # Множитель порции (например: "2 банана", "300г курицы", "3 яйца")
    multiplier = 1.0
    mult_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:г|гр|шт|порц)?", lowered)
    if mult_match:
        val = float(mult_match.group(1).replace(",", "."))
        if val > 15:  # если в граммах (например 250г)
            multiplier = val / 100.0
        elif 1 <= val <= 10:  # если в штуках
            multiplier = val

    for name, nut in FOOD_DATABASE.items():
        if name in lowered:
            found_items.append(name)
            total_cal += nut["cal"] * multiplier
            total_p += nut["p"] * multiplier
            total_f += nut["f"] * multiplier
            total_c += nut["c"] * multiplier

    if found_items:
        return {
            "food_name": f"{text.strip().capitalize()}",
            "calories": round(total_cal),
            "proteins": round(total_p, 1),
            "fats": round(total_f, 1),
            "carbs": round(total_c, 1),
            "matched": True
        }

    # 4. Эвристическая оценка неизвестного блюда
    est_cal = 280
    if any(w in lowered for w in ["салат", "овощ", "суп", "чай"]):
        est_cal = 150
    elif any(w in lowered for w in ["мясо", "плов", "пельмен", "паста", "пирог", "торт"]):
        est_cal = 550
    elif any(w in lowered for w in ["фастфуд", "шаурма", "бургер", "пицца"]):
        est_cal = 650

    return {
        "food_name": text.strip().capitalize(),
        "calories": est_cal,
        "proteins": round(est_cal * 0.20 / 4),
        "fats": round(est_cal * 0.30 / 9),
        "carbs": round(est_cal * 0.50 / 4),
        "matched": False
    }


# ---------------------------------------------------------------------------
# Генератор ПП-рецептов (Интеллектуальный конструктор под ЛЮБЫЕ ингредиенты)
# ---------------------------------------------------------------------------

BASE_STAPLE_RECIPES = [
    {
        "title": "🍳 Белковый скрэмбл с томатами и зеленью",
        "time": "10 минут",
        "calories": "~280 ккал (Б: 24г, Ж: 18г, У: 4г)",
        "ingredients": ["3 яйца", "1 помидор или томатная паста", "капля масла", "соль, перец, зелень"],
        "steps": [
            "Разогрей сковороду на среднем огне с каплей масла.",
            "Нарежь помидор кубиками и припусти 2 минуты.",
            "Взбей яйца вилкой, вылей к помидорам и помешивай лопаткой 3-4 минуты до мягкой текстуры.",
            "Посоли, поперчи и посыпь зеленью."
        ],
        "tip": "Идеальный сытный завтрак без углеводных качелей, держит сытость 4+ часа."
    },
    {
        "title": "🥣 Ленивая овсянка «Сытный заряд» с бананом и корицей",
        "time": "5 минут",
        "calories": "~340 ккал (Б: 14г, Ж: 7г, У: 55г)",
        "ingredients": ["50г геркулеса", "150мл молока или кефира", "1 банан", "корица", "горсть орехов"],
        "steps": [
            "Залей хлопья горячим молоком или с вечера холодным кефиром.",
            "Разомни половину банана вилкой в кашу для натуральной сладости.",
            "Вторую половину нарежь кружочками сверху и присыпь корицей с орехами."
        ],
        "tip": "Корица снижает тягу к сладкому и нормализует уровень сахара в крови."
    },
    {
        "title": "🥗 Быстрый салат из тунца с яйцом и огурцом",
        "time": "7 минут",
        "calories": "~310 ккал (Б: 36г, Ж: 14г, У: 6г)",
        "ingredients": ["1 банка тунца в с/с", "2 вареных яйца", "1 свежий огурец", "1 ст. л. греческого йогурта", "зелень"],
        "steps": [
            "Слей жидкость из тунца и разомни рыбу вилкой в миске.",
            "Нарежь кубиками яйца и огурец.",
            "Смешай всё с ложкой греческого йогурта, добавь щепотку соли и зеленый лук."
        ],
        "tip": "Мощная белковая бомба: идеально на ужин или после тренировки."
    },
    {
        "title": "🍗 Сочная куриная грудка в пергаменте (без масла)",
        "time": "15 минут",
        "calories": "~220 ккал (Б: 44г, Ж: 3г, У: 1г)",
        "ingredients": ["1 куриное филе (~200г)", "паприка, сушеный чеснок, соль, перец", "лист пергамента"],
        "steps": [
            "Разрежь филе вдоль пополам на плоские стейки.",
            "Натри специями и солью с обеих сторон.",
            "Заверни филе в лист пергамента и положи на сухую раскаленную сковороду.",
            "Жарь по 5-6 минут с каждой стороны на среднем огне прямо в бумаге."
        ],
        "tip": "Весь сок остается внутри, сковорода сухая, ни грамма лишнего масла!"
    }
]


def generate_pp_recipe(custom_ingredients: Optional[str] = None) -> Dict[str, any]:
    """Генерирует точный ПП-рецепт строго под введенные ингредиенты пользователя."""
    if not custom_ingredients or not custom_ingredients.strip():
        return random.choice(BASE_STAPLE_RECIPES)

    raw = custom_ingredients.strip()
    # Чистим и разбиваем на отдельные продукты
    tokens = [t.strip().capitalize() for t in re.split(r"[,;+/\n]+", raw) if len(t.strip()) > 1]
    if not tokens:
        tokens = [raw.capitalize()]

    # Формируем динамическое, кулинарно точное блюдо
    main_protein = None
    veggies = []
    carbs = []
    other = []

    for item in tokens:
        low = item.lower()
        if any(w in low for w in ["куриц", "грудк", "филе", "мясо", "говядин", "индейк", "рыб", "тунец", "яйц", "творог", "креветк"]):
            if not main_protein: main_protein = item
            else: other.append(item)
        elif any(w in low for w in ["помидор", "томат", "огур", "кабачок", "брокколи", "перц", "лук", "морков", "капуст", "гриб", "шампиньон", "шпинат", "зелен"]):
            veggies.append(item)
        elif any(w in low for w in ["рис", "гречк", "овсянк", "макарон", "картофел", "булгур", "киноа", "лаваш"]):
            carbs.append(item)
        else:
            other.append(item)

    # Придумываем привлекательное название
    title_parts = []
    if main_protein:
        title_parts.append(main_protein)
    if veggies:
        title_parts.append(f"с {veggies[0].lower()}" + (f" и {veggies[1].lower()}" if len(veggies) > 1 else ""))
    if carbs:
        title_parts.append(f"на подушке из {carbs[0].lower()}")

    if not title_parts:
        title = f"🥗 ПП-блюдо из: {', '.join(tokens[:3])}"
    else:
        title = f"🍽 Сбалансированный ПП-обед: {' '.join(title_parts)}"

    # Собираем список ингредиентов
    ings_output = [f"• {t}" for t in tokens]
    ings_output.extend(["• 1 ч. л. оливкового масла (для тушения)", "• Соль, смесь перцев, сушеный чеснок / паприка по вкусу"])

    # Пошаговая инструкция под состав
    steps = []
    if carbs:
        steps.append(f"1. Отвари {carbs[0].lower()} в подсоленной воде до состояния al dente (сохраняет медленные углеводы).")

    if main_protein and veggies:
        steps.append(f"2. {main_protein} нарежь небольшими кусочками, посыпь специями и обжарь на сухой сковороде с каплей масла 5-7 минут.")
        steps.append(f"3. Нарежь {', '.join([v.lower() for v in veggies])}, добавь в сковороду, убавь огонь и туши под крышкой 5-6 минут (овощи останутся сочными и богатыми клетчаткой).")
    elif main_protein:
        steps.append(f"2. {main_protein} замаринуй со специями и обжарь или запеки 12-15 минут до золотистой корочки.")
    elif veggies:
        steps.append(f"2. Нарежь {', '.join([v.lower() for v in veggies])}, быстро спассеруй на сковороде или сделай хрустящий свежий салат.")
    else:
        steps.append(f"2. Соедини все ингредиенты ({', '.join(tokens)}), приправь специями и доведи до готовности на среднем огне 10-12 минут.")

    if carbs:
        steps.append("4. Выложи всё на тарелку по «правилу здоровой тарелки»: 50% овощи, 25% белок, 25% углеводы.")
    else:
        steps.append("3. Подавай горячим, по желанию добавив свежую зелень или ложку греческого йогурта.")

    # Оценка калорийности
    est_cal = 320
    if main_protein: est_cal += 120
    if carbs: est_cal += 150
    prot_est = 35 if main_protein else 15
    fats_est = 12
    carbs_est = 45 if carbs else 15

    return {
        "title": title,
        "time": "15-20 минут",
        "calories": f"~{est_cal} ккал (Б: {prot_est}г, Ж: {fats_est}г, У: {carbs_est}г)",
        "ingredients": ings_output,
        "steps": steps,
        "tip": "Правило сытости: начинай трапезу с овощей и белка — клетчатка замедлит усвоение, и ты будешь сыт в 2 раза дольше!"
    }
