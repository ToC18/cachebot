from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional
from pydantic import BaseModel


class SalaryDistributionResult(BaseModel):
    commute_frozen: Decimal
    fixed_commitments_frozen: Decimal
    net_base: Decimal
    savings_locked: Decimal
    discretionary_budget: Decimal
    days_in_cycle: int
    daily_safe_spend: Decimal
    hourly_rate: Decimal


class PartialIncomeResult(BaseModel):
    total_received: Decimal
    savings_locked: Decimal
    discretionary_added: Decimal
    days_in_cycle: int
    new_daily_safe_spend: Decimal


class CrisisResolutionResult(BaseModel):
    overspent_amount: Decimal
    action_taken: str
    updated_daily_limit: Decimal
    remaining_days: int
    weekend_fund_remaining: Decimal


class FinanceEngine:
    @staticmethod
    def calculate_days_until_payday(
        today: date, 
        target_date: Optional[date] = None, 
        payday_day: int = 10
    ) -> int:
        """
        Calculates exact days until the next payday or specific target payout date.
        """
        if target_date and target_date >= today:
            days = (target_date - today).days
            return max(days, 1)

        if today.day < payday_day:
            next_payday = date(today.year, today.month, payday_day)
        else:
            if today.month == 12:
                next_payday = date(today.year + 1, 1, payday_day)
            else:
                next_payday = date(today.year, today.month + 1, payday_day)
        days = (next_payday - today).days
        return max(days, 1)

    @classmethod
    def process_salary_pipeline(
        cls,
        salary: Decimal,
        work_shifts: int,
        roundtrip_commute_fare: Decimal,
        fixed_commitments_total: Decimal,
        savings_percent: Decimal,
        today: date,
        payday_day: int = 10,
        target_date: Optional[date] = None,
        working_hours: int = 168
    ) -> SalaryDistributionResult:
        """
        Step 1: Forward commitments (Commute + Fixed Obligations).
        Step 2: Pay Yourself First (20% of Net Base locked into Savings).
        Step 3: Drip-Feeding (Safe-to-Spend daily limit).
        """
        commute_total = (Decimal(work_shifts) * roundtrip_commute_fare).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_frozen = commute_total + fixed_commitments_total
        
        net_base = max(salary - total_frozen, Decimal("0.00"))
        
        hourly_rate = (net_base / Decimal(working_hours)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        savings_multiplier = savings_percent / Decimal("100.00")
        savings_locked = (net_base * savings_multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        discretionary_budget = net_base - savings_locked
        days_left = cls.calculate_days_until_payday(today, target_date, payday_day)
        daily_safe_spend = (discretionary_budget / Decimal(days_left)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        
        return SalaryDistributionResult(
            commute_frozen=commute_total,
            fixed_commitments_frozen=fixed_commitments_total,
            net_base=net_base,
            savings_locked=savings_locked,
            discretionary_budget=discretionary_budget,
            days_in_cycle=days_left,
            daily_safe_spend=daily_safe_spend,
            hourly_rate=hourly_rate
        )

    @classmethod
    def process_partial_income(
        cls,
        income_amount: Decimal,
        current_daily_limit: Decimal,
        savings_percent: Decimal,
        today: date,
        target_date: Optional[date] = None,
        payday_day: int = 10
    ) -> PartialIncomeResult:
        """
        Processes advance or partial income without freezing whole month commute/fixed costs.
        """
        savings_multiplier = savings_percent / Decimal("100.00")
        savings_locked = (income_amount * savings_multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discretionary_added = income_amount - savings_locked

        days_left = cls.calculate_days_until_payday(today, target_date, payday_day)
        
        # New daily safe limit = existing daily limit + (new amount / remaining days)
        added_daily = (discretionary_added / Decimal(days_left)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        new_daily = current_daily_limit + added_daily

        return PartialIncomeResult(
            total_received=income_amount,
            savings_locked=savings_locked,
            discretionary_added=discretionary_added,
            days_in_cycle=days_left,
            new_daily_safe_spend=new_daily
        )

    @staticmethod
    def calculate_work_hours_paywall(price: Decimal, hourly_rate: Decimal, item_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Killer Feature 1: Smart Paywall
        Translates cost into work hours and shifts.
        """
        if hourly_rate <= Decimal("0.00"):
            return {
                "hours": Decimal("0.0"),
                "days": Decimal("0.0"),
                "formatted_message": (
                    "⚠️ Чистая ставка в час пока не рассчитана.\n"
                    "Внеси зарплату через кнопку 💼 «Внести доход»."
                )
            }
            
        hours_cost = (price / hourly_rate).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        work_days = (hours_cost / Decimal("8.0")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        
        item_prefix = f"«{item_name}» стоит" if item_name else "Эта покупка стоит"
        message = (
            f"🛒 **Умный Paywall**\n\n"
            f"{item_prefix} **{price} BYN**.\n\n"
            f"⏳ Это эквивалентно **{hours_cost} ч.** твоей чистой работы "
            f"(~**{work_days}** полных 8-часовых смен за монитором и в дороге).\n\n"
            f"Они действительно стоят этого времени жизни?"
        )
        return {
            "hours": hours_cost,
            "days": work_days,
            "formatted_message": message
        }

    @staticmethod
    def resolve_crisis_mode(
        overspent_amount: Decimal,
        weekly_remaining_budget: Decimal,
        remaining_days_in_week: int,
        weekend_fund_balance: Decimal,
        strategy: str
    ) -> CrisisResolutionResult:
        safe_days = max(remaining_days_in_week, 1)

        if strategy == "COVER_BY_WEEKEND_FUND":
            amount_from_weekend = min(overspent_amount, weekend_fund_balance)
            new_weekend_balance = weekend_fund_balance - amount_from_weekend
            uncovered_debt = overspent_amount - amount_from_weekend
            
            updated_limit = max(
                (weekly_remaining_budget - uncovered_debt) / Decimal(safe_days),
                Decimal("0.00")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
            return CrisisResolutionResult(
                overspent_amount=overspent_amount,
                action_taken=f"Покрыто из фонда выходных: {amount_from_weekend} BYN",
                updated_daily_limit=updated_limit,
                remaining_days=safe_days,
                weekend_fund_remaining=new_weekend_balance
            )
        else:
            adjusted_weekly = weekly_remaining_budget - overspent_amount
            new_daily_limit = max(
                adjusted_weekly / Decimal(safe_days), 
                Decimal("0.00")
            ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            
            return CrisisResolutionResult(
                overspent_amount=overspent_amount,
                action_taken="Лимиты на оставшиеся дни недели снижены для сохранения баланса",
                updated_daily_limit=new_daily_limit,
                remaining_days=safe_days,
                weekend_fund_remaining=weekend_fund_balance
            )
