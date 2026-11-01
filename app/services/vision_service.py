import json
from decimal import Decimal
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
import google.generativeai as genai
from app.config import settings


class ExtractedTransactionType(str, Enum):
    EXPENSE = "EXPENSE"
    TRANSFER_TO_CASH = "TRANSFER_TO_CASH"
    COMMUTE_EXPENSE = "COMMUTE_EXPENSE"
    INCOME = "INCOME"


class ParsedTransactionItem(BaseModel):
    amount: float = Field(description="Сумма операции (например 12.50)")
    type: ExtractedTransactionType = Field(description="Тип операции: EXPENSE, TRANSFER_TO_CASH, COMMUTE_EXPENSE, INCOME")
    category: str = Field(description="Категория: Супермаркеты, Транспорт, Услуги, Кафе")
    merchant: Optional[str] = Field(description="Торговая точка: Евроопт, AUTOSTAN, ATM")
    needs_clarification: bool = Field(description="True если требуется ручное уточнение")
    raw_text: str = Field(description="Исходная строка")

    @property
    def decimal_amount(self) -> Decimal:
        return Decimal(str(round(self.amount, 2)))


class VisionAnalysisResult(BaseModel):
    document_type: str = Field(description="RECEIPT, BANK_STATEMENT, SALARY_NOTIFICATION или OTHER")
    currency: str = Field(description="Валюта документа, например BYN")
    items: List[ParsedTransactionItem] = Field(description="Список распознанных операций")


class GeminiVisionService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.model = None

        if self.api_key and self.api_key != "your_gemini_api_key_here":
            genai.configure(api_key=self.api_key)
            system_instruction = """
            Ты — финансовый эксперт-парсер чеков и банковских выписок.
            Твоя задача — извлечь список финансовых транзакций из изображения.

            ПРАВИЛА ОБРАБОТКИ:
            1. ЧЕК ИЗ МАГАЗИНА:
               - Извлекай ТОЛЬКО итоговую сумму (ИТОГ / К ОПЛАТЕ / ВСЕГО). Не дроби позиции чека.
               - document_type: "RECEIPT"
               - type: EXPENSE
               - category: "Супермаркеты / Продукты"
               - merchant: Название магазина (например, "Евроопт", "Копеечка", "Санта", "Соседи").
            
            2. СКРИНШОТ БАНКОВСКОЙ ВЫПИСКИ / ПРИЛОЖЕНИЯ:
               - document_type: "BANK_STATEMENT"
               - Банкоматы / Снятие ('ATM', 'Банкомат', 'ВЫДАЧА НАЛИЧНЫХ') -> type: TRANSFER_TO_CASH, category: "Наличные".
               - Пригородный транспорт / Дорога ('AUTOSTAN', 'Электричка', 'Минсктранс') -> type: COMMUTE_EXPENSE, category: "Транспорт".
               - Обезличенные платежи ('OPLATA USLUG', 'ЕРИП', 'e-pay') -> category: "Услуги / Счета", needs_clarification: true.
               - Зачисление зарплаты ('ZARPLATA', 'ZACHISLENIE', 'Зачисление зарплаты') -> type: INCOME, category: "Доход".
            
            3. СКРИНШОТ О ЗАРПЛАТЕ:
               - document_type: "SALARY_NOTIFICATION"
               - type: INCOME
               - category: "Доход / Зарплата"
            """
            self.model = genai.GenerativeModel(
                model_name="gemini-3.5-flash-lite",
                system_instruction=system_instruction,
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": VisionAnalysisResult,
                    "temperature": 0.1,
                }
            )

    async def analyze_image(self, image_bytes: bytes, mime_type: str = "image/jpeg") -> VisionAnalysisResult:
        if not self.model:
            raise ValueError("GEMINI_API_KEY не сконфигурирован в .env")

        contents = [
            {"mime_type": mime_type, "data": image_bytes},
            "Извлеки структурированные данные о транзакциях строго по схеме."
        ]
        
        response = await self.model.generate_content_async(contents)
        result_json = json.loads(response.text)
        return VisionAnalysisResult(**result_json)
