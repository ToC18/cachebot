import re
import json
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field
import google.generativeai as genai
from app.config import settings


class ParsedExpenseItem(BaseModel):
    amount: float = Field(description="Сумма расхода числом, например 14.0 или 4.5")
    category: str = Field(description="Категория: Транспорт, Кафе и еда, Супермаркеты")
    description: str = Field(description="Краткое описание товара или услуги")


class ParsedExpensesResponse(BaseModel):
    items: List[ParsedExpenseItem] = Field(description="Список расходов")


class FreeTextParserService:
    def __init__(self):
        self.model = None
        if settings.gemini_api_key and settings.gemini_api_key != "your_gemini_api_key_here":
            genai.configure(api_key=settings.gemini_api_key)
            self.model = genai.GenerativeModel(
                model_name="gemini-3.5-flash-lite",
                system_instruction="""
                Ты финансовый помощник. Извлекай список трат из свободной фразы пользователя.
                Примеры:
                "14 маршрутка" -> items: [{"amount": 14.0, "category": "Транспорт", "description": "маршрутка"}]
                "обед 12 и кофе 4.5" -> items: [
                   {"amount": 12.0, "category": "Кафе и еда", "description": "обед"},
                   {"amount": 4.5, "category": "Кафе и еда", "description": "кофе"}
                ]
                """,
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": ParsedExpensesResponse,
                    "temperature": 0.0
                }
            )

    def fast_regex_parse(self, text: str) -> Optional[List[dict]]:
        """Fast offline heuristic parser for simple cases like '14 маршрутка' or 'кофе 4.5'"""
        text = text.strip()
        
        # Match '14 маршрутка' or '14.50 такси'
        match1 = re.match(r"^(\d+(?:[.,]\d{1,2})?)\s+([a-zA-Zа-яА-ЯёЁ\s]+)$", text)
        if match1:
            amount = Decimal(match1.group(1).replace(",", "."))
            desc = match1.group(2).strip()
            return [{"amount": amount, "category": self._guess_category(desc), "description": desc}]
            
        # Match 'маршрутка 14' or 'такси 14.50'
        match2 = re.match(r"^([a-zA-Zа-яА-ЯёЁ\s]+)\s+(\d+(?:[.,]\d{1,2})?)$", text)
        if match2:
            desc = match2.group(1).strip()
            amount = Decimal(match2.group(2).replace(",", "."))
            return [{"amount": amount, "category": self._guess_category(desc), "description": desc}]

        return None

    def _guess_category(self, desc: str) -> str:
        d = desc.lower()
        if any(w in d for w in ["маршрутк", "автобус", "такси", "электричк", "метро", "проезд", "дорог"]):
            return "Транспорт"
        if any(w in d for w in ["кофе", "обед", "ужин", "шаурм", "пицц", "бургер", "кафе", "столов"]):
            return "Кафе и еда"
        if any(w in d for w in ["магазин", "продукты", "хлеб", "молоко", "еда", "евроопт", "копеечк"]):
            return "Супермаркеты / Продукты"
        if any(w in d for w in ["аптек", "лекарств", "таблетк"]):
            return "Здоровье"
        return "Разное"

    async def parse_text(self, text: str) -> List[dict]:
        fast_result = self.fast_regex_parse(text)
        if fast_result:
            return fast_result

        if self.model:
            try:
                response = await self.model.generate_content_async(text)
                res_dict = json.loads(response.text)
                parsed_resp = ParsedExpensesResponse(**res_dict)
                return [
                    {
                        "amount": Decimal(str(round(item.amount, 2))),
                        "category": item.category,
                        "description": item.description
                    }
                    for item in parsed_resp.items
                ]
            except Exception:
                pass

        num_match = re.search(r"(\d+(?:[.,]\d{1,2})?)", text)
        if num_match:
            amount = Decimal(num_match.group(1).replace(",", "."))
            desc = text.replace(num_match.group(1), "").strip() or "Расход"
            return [{"amount": amount, "category": self._guess_category(desc), "description": desc}]

        return []
