import os
import re
import uuid
from datetime import date, datetime, time as dtime
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select, delete
from typing import Optional, Dict, List

from app.database.session import async_session_maker
from app.database.models import (
    User, Envelope, EnvelopeType, Transaction, TransactionType, TransactionSource,
    Obligation, ObligationType, Debt, DebtType, Goal, ShoppingReminder, HabitReminder, HabitType, FoodLog
)
from app.services.finance_engine import FinanceEngine
from app.services.redis_service import redis_client
from app.services.smart_assistant import (
    classify_expense, decide_randomizer, estimate_goal_months, generate_pp_recipe, calculate_weight_loss_plan, parse_food_input
)
from app.api.telegram_auth import get_telegram_user

router = APIRouter()


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------

class ExpenseRequest(BaseModel):
    amount: float
    description: str
    envelope_type: Optional[str] = "daily"  # "daily", "commute", "weekend"

class CommuteExpenseRequest(BaseModel):
    amount: Optional[float] = None
    description: Optional[str] = "Проезд"

class CommuteTopupRequest(BaseModel):
    amount: float

class WeekendDepositRequest(BaseModel):
    amount: float
    from_daily: bool = True

class WeekendWithdrawRequest(BaseModel):
    amount: float
    description: Optional[str] = "Траты на выходных"


class IncomeRequest(BaseModel):
    amount: float
    income_type: str = "full_salary"


class SettingsRequest(BaseModel):
    payday_day: int
    savings_percent: float
    show_hourly_rate: Optional[bool] = None
    roundtrip_commute_fare: Optional[float] = None
    work_shifts_per_month: Optional[int] = None
    weight_kg: Optional[float] = None
    target_weight_kg: Optional[float] = None
    height_cm: Optional[int] = None


class EmergencyWithdrawRequest(BaseModel):
    amount: float
    reason: str


class DebtCreateRequest(BaseModel):
    debt_type: str  # "I_OWE" or "OWES_ME"
    person_name: str
    amount: float
    comment: Optional[str] = None


class ObligationCreateRequest(BaseModel):
    obligation_type: str  # "INSTALLMENT", "CREDIT", "SUBSCRIPTION", "CONSUMABLE"
    title: str
    monthly_amount: float
    months_left: Optional[int] = None


class GoalCreateRequest(BaseModel):
    title: str
    target_amount: float


class ShoppingReminderRequest(BaseModel):
    items: str
    time_str: str  # "18:30" (МСК)


class HabitReminderRequest(BaseModel):
    habit_type: str  # "WARMUP", "WORKOUT", "WATER", "STRETCH"
    title: str
    time_str: str    # "08:30" (МСК)


class RecipeRequest(BaseModel):
    ingredients: Optional[str] = None



class FoodLogCreateRequest(BaseModel):
    text: Optional[str] = None
    food_name: Optional[str] = None
    calories: Optional[float] = None
    proteins: Optional[float] = None
    fats: Optional[float] = None
    carbs: Optional[float] = None
    source: Optional[str] = "manual"

class HealthProfileRequest(BaseModel):
    weight_kg: float
    target_weight_kg: float
    height_cm: int
    age: Optional[int] = 25
    gender: Optional[str] = "male"
    activity_level: Optional[str] = "moderate"

class RandomizerRequest(BaseModel):
    item: Optional[str] = None


# ---------------------------------------------------------------------------
# Serve HTML
# ---------------------------------------------------------------------------

@router.get("/app")
async def serve_mini_app():
    return FileResponse(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "index.html"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


# ---------------------------------------------------------------------------
# Full Dashboard Aggregate (for single fast load)
# ---------------------------------------------------------------------------

@router.get("/api/me/dashboard")
async def get_user_dashboard(tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    today = date.today()

    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()

        if not user:
            user = User(
                id=user_id,
                username=tg_user.get("username"),
                first_name=tg_user.get("first_name"),
                currency="BYN",
                monthly_working_hours=168,
                work_shifts_per_month=22,
                roundtrip_commute_fare=Decimal("0.00"),
                payday_day_of_month=10,
                savings_target_percent=Decimal("20.00"),
                show_hourly_rate=True
            )
            session.add(user)
            await session.commit()

        # Envelopes
        env_stmt = select(Envelope).where(Envelope.user_id == user_id)
        envelopes = {e.type: e for e in (await session.execute(env_stmt)).scalars().all()}

        # Category breakdown
        tx_stmt = select(Transaction).where(
            Transaction.user_id == user_id,
            Transaction.type == TransactionType.EXPENSE
        )
        txs = (await session.execute(tx_stmt)).scalars().all()
        category_breakdown: Dict[str, float] = {}
        for t in txs:
            cat = t.category or "💡 Прочее"
            if cat in ["Расход из Mini App", "EXPENSE", "Расход"]:
                cat = classify_expense(f"{t.merchant or ''} {t.raw_input_text or ''}")
            clean_name = cat.split(" ", 1)[-1] if " " in cat else cat
            category_breakdown[clean_name] = category_breakdown.get(clean_name, 0.0) + float(t.amount)

        # Debts
        debts_stmt = select(Debt).where(Debt.user_id == user_id, Debt.is_closed == False)
        active_debts = (await session.execute(debts_stmt)).scalars().all()
        i_owe_list = [
            {"id": str(d.id), "person": d.person_name, "amount": float(d.remaining_amount), "comment": d.comment or ""}
            for d in active_debts if d.debt_type == DebtType.I_OWE
        ]
        owes_me_list = [
            {"id": str(d.id), "person": d.person_name, "amount": float(d.remaining_amount), "comment": d.comment or ""}
            for d in active_debts if d.debt_type == DebtType.OWES_ME
        ]

        # Obligations (Credits + Consumables)
        oblg_stmt = select(Obligation).where(Obligation.user_id == user_id, Obligation.is_active == True)
        obls = (await session.execute(oblg_stmt)).scalars().all()
        obligations_list = [
            {
                "id": str(o.id),
                "title": o.title,
                "amount": float(o.monthly_amount),
                "type": o.obligation_type.value,
                "months_left": o.months_left
            }
            for o in obls
        ]

        # Goals + ETA
        monthly_savings = (user.current_cycle_net_base * (user.savings_target_percent / Decimal("100.00"))).quantize(Decimal("0.01"))
        goals_stmt = select(Goal).where(Goal.user_id == user_id)
        goals = (await session.execute(goals_stmt)).scalars().all()
        goals_list = []
        for g in goals:
            eta = estimate_goal_months(g.target_amount, g.current_amount, monthly_savings)
            goals_list.append({
                "id": str(g.id),
                "title": g.title,
                "target": float(g.target_amount),
                "current": float(g.current_amount),
                "months_left": eta["months"],
                "eta_text": eta["formatted"]
            })

        # Shopping reminders
        shop_stmt = select(ShoppingReminder).where(ShoppingReminder.user_id == user_id, ShoppingReminder.is_sent == False)
        shop_reminders = (await session.execute(shop_stmt)).scalars().all()
        shopping_list = [
            {
                "id": str(s.id),
                "items": s.items_text,
                "time": s.remind_at.strftime("%H:%M (%d.%m)")
            }
            for s in shop_reminders
        ]

        # Habit reminders
        habit_stmt = select(HabitReminder).where(HabitReminder.user_id == user_id, HabitReminder.is_active == True)
        habits = (await session.execute(habit_stmt)).scalars().all()
        habits_list = [
            {
                "id": str(h.id),
                "title": h.title,
                "type": h.habit_type.value,
                "time": h.remind_time.strftime("%H:%M")
            }
            for h in habits
        ]

        # Food logs for today
        today_start = datetime(today.year, today.month, today.day, 0, 0, 0)
        food_stmt = select(FoodLog).where(
            FoodLog.user_id == user_id,
            FoodLog.logged_at >= today_start
        ).order_by(FoodLog.logged_at.desc())
        food_records = (await session.execute(food_stmt)).scalars().all()
        food_today_list = [
            {
                "id": str(f.id),
                "food_name": f.food_name,
                "calories": float(f.calories),
                "proteins": float(f.proteins),
                "fats": float(f.fats),
                "carbs": float(f.carbs),
                "source": f.source,
                "time": f.logged_at.strftime("%H:%M")
            }
            for f in food_records
        ]
        total_cals = sum(f["calories"] for f in food_today_list)
        total_p = sum(f["proteins"] for f in food_today_list)
        total_f = sum(f["fats"] for f in food_today_list)
        total_c = sum(f["carbs"] for f in food_today_list)

        # Weight loss plan
        weight_plan = None
        if user.weight_kg and user.target_weight_kg:
            weight_plan = calculate_weight_loss_plan(
                current_weight=float(user.weight_kg),
                target_weight=float(user.target_weight_kg),
                height_cm=user.height_cm or 175,
                age=user.age or 25,
                gender=user.gender or "male",
                activity_level=user.activity_level or "moderate"
            )

    today_spent = await redis_client.get_today_spent(user_id)
    days_left = FinanceEngine.calculate_days_until_payday(
        today=today, 
        target_date=user.next_payday_date, 
        payday_day=user.payday_day_of_month
    )

    has_budget = bool(user.daily_safe_spend_limit and user.daily_safe_spend_limit > Decimal("0.00"))
    total_oblg_sum = sum(float(o["amount"]) for o in obligations_list)
    fixed_env_bal = float(envelopes.get(EnvelopeType.FIXED_COMMITMENT).current_balance) if envelopes.get(EnvelopeType.FIXED_COMMITMENT) else 0.0
    effective_fixed = max(fixed_env_bal, total_oblg_sum)

    return {
        "user_id": user_id,
        "first_name": user.first_name or tg_user.get("first_name") or "Друг",
        "currency": user.currency,
        "has_budget": has_budget,
        "show_hourly_rate": user.show_hourly_rate,
        "roundtrip_commute_fare": float(user.roundtrip_commute_fare or 0.0),
        "work_shifts": user.work_shifts_per_month or 22,
        "daily_safe_spend_limit": float(user.daily_safe_spend_limit or 0),
        "today_spent": float(today_spent),
        "current_hourly_rate": float(user.current_hourly_rate or 0),
        "days_left": days_left,
        "payday_day_of_month": user.payday_day_of_month,
        "savings_target_percent": float(user.savings_target_percent),
        "category_breakdown": category_breakdown,
        "health": {
            "weight_kg": float(user.weight_kg) if user.weight_kg else None,
            "target_weight_kg": float(user.target_weight_kg) if user.target_weight_kg else None,
            "height_cm": user.height_cm,
            "age": user.age or 25,
            "gender": user.gender or "male",
            "activity_level": user.activity_level or "moderate",
            "daily_calorie_target": user.daily_calorie_target or (weight_plan["target_calories"] if weight_plan else 1800),
        },
        "weight_plan": weight_plan,
        "nutrition_today": {
            "calories": round(total_cals, 1),
            "proteins": round(total_p, 1),
            "fats": round(total_f, 1),
            "carbs": round(total_c, 1),
            "logs": food_today_list
        },

        "envelopes": {
            "savings": float(envelopes.get(EnvelopeType.SAVINGS).current_balance) if envelopes.get(EnvelopeType.SAVINGS) else 0.0,
            "weekend_fund": float(envelopes.get(EnvelopeType.WEEKEND_FUND).current_balance) if envelopes.get(EnvelopeType.WEEKEND_FUND) else 0.0,
            "commute": float(envelopes.get(EnvelopeType.COMMUTE).current_balance) if envelopes.get(EnvelopeType.COMMUTE) else 0.0,
            "fixed_commitment": round(effective_fixed, 2),
            "daily_safe_spend": float(envelopes.get(EnvelopeType.DAILY_SAFE_SPEND).current_balance) if envelopes.get(EnvelopeType.DAILY_SAFE_SPEND) else 0.0,
        },
        "debts": {
            "i_owe": i_owe_list,
            "owes_me": owes_me_list,
            "total_i_owe": sum(d["amount"] for d in i_owe_list),
            "total_owes_me": sum(d["amount"] for d in owes_me_list),
        },
        "obligations": obligations_list,
        "goals": goals_list,
        "shopping_reminders": shopping_list,
        "habit_reminders": habits_list
    }


# ---------------------------------------------------------------------------
# Basic Transactions
# ---------------------------------------------------------------------------

@router.post("/api/me/expense")
async def add_expense_from_app(req: ExpenseRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    amount_dec = Decimal(str(round(req.amount, 2)))
    category = classify_expense(req.description)
    env_type_str = (req.envelope_type or "daily").lower()

    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        today_spent = await redis_client.get_today_spent(user_id)
        envelope_id = None

        if env_type_str == "commute":
            category = "🚕 Транспорт и Бензин"
            env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.COMMUTE)
            commute_env = (await session.execute(env_stmt)).scalar_one_or_none()
            if not commute_env:
                commute_env = Envelope(
                    user_id=user_id,
                    name="Транспорт",
                    type=EnvelopeType.COMMUTE,
                    allocated_amount=Decimal("0.00"),
                    current_balance=Decimal("0.00")
                )
                session.add(commute_env)
                await session.flush()
            commute_env.current_balance = max(commute_env.current_balance - amount_dec, Decimal("0.00"))
            envelope_id = commute_env.id
        elif env_type_str == "weekend":
            category = "🎉 Развлечения и Отдых"
            env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.WEEKEND_FUND)
            weekend_env = (await session.execute(env_stmt)).scalar_one_or_none()
            if not weekend_env:
                weekend_env = Envelope(
                    user_id=user_id,
                    name="Фонд выходных",
                    type=EnvelopeType.WEEKEND_FUND,
                    allocated_amount=Decimal("0.00"),
                    current_balance=Decimal("0.00")
                )
                session.add(weekend_env)
                await session.flush()
            weekend_env.current_balance = max(weekend_env.current_balance - amount_dec, Decimal("0.00"))
            envelope_id = weekend_env.id
        else:
            # Default: daily safe spend
            env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.DAILY_SAFE_SPEND)
            safe_env = (await session.execute(env_stmt)).scalar_one_or_none()
            if safe_env:
                safe_env.current_balance = max(safe_env.current_balance - amount_dec, Decimal("0.00"))
            envelope_id = safe_env.id if safe_env else None
            today_spent = await redis_client.add_today_spent(user_id, amount_dec)

        tx = Transaction(
            user_id=user_id,
            envelope_id=envelope_id,
            amount=amount_dec,
            type=TransactionType.EXPENSE,
            source=TransactionSource.MANUAL_TEXT,
            category=category,
            merchant=req.description
        )
        session.add(tx)
        await session.commit()

    return {"status": "OK", "today_spent": float(today_spent), "category": category}


class CommuteFareRequest(BaseModel):
    roundtrip_commute_fare: float
    work_shifts: Optional[int] = None

@router.post("/api/me/commute/fare")
async def update_commute_fare(req: CommuteFareRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.roundtrip_commute_fare = Decimal(str(round(req.roundtrip_commute_fare, 2)))
        if req.work_shifts and req.work_shifts > 0:
            user.work_shifts_per_month = req.work_shifts
        await session.commit()
    return {"status": "OK", "roundtrip_commute_fare": float(user.roundtrip_commute_fare)}

@router.post("/api/me/commute/expense")
async def add_commute_trip(req: CommuteExpenseRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        fare = req.amount
        if fare is None or fare <= 0:
            if user.roundtrip_commute_fare and user.roundtrip_commute_fare > Decimal("0.00"):
                fare = float(user.roundtrip_commute_fare) / 2.0
            else:
                fare = 1.0  # default 1 BYN

        amount_dec = Decimal(str(round(fare, 2)))
        env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.COMMUTE)
        env = (await session.execute(env_stmt)).scalar_one_or_none()
        if not env:
            env = Envelope(
                user_id=user_id,
                name="Транспорт",
                type=EnvelopeType.COMMUTE,
                allocated_amount=Decimal("0.00"),
                current_balance=Decimal("0.00")
            )
            session.add(env)
            await session.flush()

        env.current_balance = max(env.current_balance - amount_dec, Decimal("0.00"))

        tx = Transaction(
            user_id=user_id,
            envelope_id=env.id,
            amount=amount_dec,
            type=TransactionType.EXPENSE,
            source=TransactionSource.MANUAL_TEXT,
            category="🚕 Транспорт и Бензин",
            merchant=req.description or "Проезд на транспорте"
        )
        session.add(tx)
        await session.commit()
        bal = float(env.current_balance)

    return {"status": "OK", "commute_balance": bal, "amount_spent": float(amount_dec)}


@router.post("/api/me/commute/topup")
async def topup_commute_envelope(req: CommuteTopupRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    amount_dec = Decimal(str(round(req.amount, 2)))
    if amount_dec <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    async with async_session_maker() as session:
        env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.COMMUTE)
        env = (await session.execute(env_stmt)).scalar_one_or_none()
        if not env:
            env = Envelope(
                user_id=user_id,
                name="Транспорт",
                type=EnvelopeType.COMMUTE,
                allocated_amount=amount_dec,
                current_balance=amount_dec
            )
            session.add(env)
        else:
            env.allocated_amount += amount_dec
            env.current_balance += amount_dec

        tx = Transaction(
            user_id=user_id,
            envelope_id=env.id,
            amount=amount_dec,
            type=TransactionType.INCOME,
            source=TransactionSource.MANUAL_TEXT,
            category="🚕 Транспорт и Бензин",
            merchant="Пополнение транспортного конверта"
        )
        session.add(tx)
        await session.commit()
        bal = float(env.current_balance)

    return {"status": "OK", "commute_balance": bal}


@router.post("/api/me/weekend-fund/deposit")
async def deposit_to_weekend_fund(req: WeekendDepositRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    amount_dec = Decimal(str(round(req.amount, 2)))
    if amount_dec <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    async with async_session_maker() as session:
        if req.from_daily:
            daily_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.DAILY_SAFE_SPEND)
            daily_env = (await session.execute(daily_stmt)).scalar_one_or_none()
            if daily_env:
                daily_env.current_balance = max(daily_env.current_balance - amount_dec, Decimal("0.00"))
            await redis_client.add_today_spent(user_id, amount_dec)

        env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.WEEKEND_FUND)
        env = (await session.execute(env_stmt)).scalar_one_or_none()
        if not env:
            env = Envelope(
                user_id=user_id,
                name="Фонд выходных",
                type=EnvelopeType.WEEKEND_FUND,
                allocated_amount=amount_dec,
                current_balance=amount_dec
            )
            session.add(env)
        else:
            env.allocated_amount += amount_dec
            env.current_balance += amount_dec

        tx = Transaction(
            user_id=user_id,
            envelope_id=env.id,
            amount=amount_dec,
            type=TransactionType.REALLOCATION,
            source=TransactionSource.MANUAL_TEXT,
            category="🎉 Развлечения и Отдых",
            merchant="Отложено в фонд выходных"
        )
        session.add(tx)
        await session.commit()
        bal = float(env.current_balance)

    return {"status": "OK", "weekend_balance": bal}


@router.post("/api/me/weekend-fund/withdraw")
async def withdraw_from_weekend_fund(req: WeekendWithdrawRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    amount_dec = Decimal(str(round(req.amount, 2)))
    if amount_dec <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Сумма должна быть больше нуля")

    async with async_session_maker() as session:
        env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.WEEKEND_FUND)
        env = (await session.execute(env_stmt)).scalar_one_or_none()
        if not env or env.current_balance <= Decimal("0.00"):
            raise HTTPException(status_code=400, detail="В фонде выходных пока нет накопленных средств")
        if env.current_balance < amount_dec:
            raise HTTPException(status_code=400, detail=f"В фонде выходных доступно только {env.current_balance} BYN")

        env.current_balance -= amount_dec

        tx = Transaction(
            user_id=user_id,
            envelope_id=env.id,
            amount=amount_dec,
            type=TransactionType.EXPENSE,
            source=TransactionSource.MANUAL_TEXT,
            category="🎉 Развлечения и Отдых",
            merchant=req.description or "Траты из фонда выходных"
        )
        session.add(tx)
        await session.commit()
        bal = float(env.current_balance)

    return {"status": "OK", "weekend_balance": bal}


@router.post("/api/me/income")
async def add_income_from_app(req: IncomeRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    amount_dec = Decimal(str(round(req.amount, 2)))
    today = date.today()

    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        oblg_stmt = select(Obligation).where(Obligation.user_id == user_id, Obligation.is_active == True)
        obligations = (await session.execute(oblg_stmt)).scalars().all()
        obligations_total = sum(o.monthly_amount for o in obligations)

        if req.income_type == "full_salary":
            res = FinanceEngine.process_salary_pipeline(
                salary=amount_dec,
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
                        allocated_amount=allocated,
                        current_balance=allocated
                    )
                    session.add(env)
                else:
                    env.allocated_amount = allocated
                    env.current_balance = allocated
        else:
            partial_res = FinanceEngine.process_partial_income(
                income_amount=amount_dec,
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

        tx = Transaction(
            user_id=user_id,
            amount=amount_dec,
            type=TransactionType.INCOME,
            source=TransactionSource.MANUAL_TEXT,
            category="Доход / Зарплата",
            merchant=f"Пополнение через Mini App ({req.income_type})"
        )
        session.add(tx)
        await session.commit()

    return {"status": "OK", "new_daily_limit": float(user.daily_safe_spend_limit)}


# ---------------------------------------------------------------------------
# Фича 2: Вычет из подушки безопасности (Emergency withdraw)
# ---------------------------------------------------------------------------

@router.post("/api/me/emergency-withdraw")
async def emergency_withdraw(req: EmergencyWithdrawRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    amount_dec = Decimal(str(round(req.amount, 2)))
    if amount_dec <= Decimal("0.00"):
        raise HTTPException(status_code=400, detail="Укажите продукт или текст приема")

    async with async_session_maker() as session:
        env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.SAVINGS)
        s_env = (await session.execute(env_stmt)).scalar_one_or_none()
        if not s_env or s_env.current_balance < amount_dec:
            cur = float(s_env.current_balance) if s_env else 0.0
            raise HTTPException(status_code=400, detail=f"В подушке недостаточно средств! Баланс: {cur} BYN")

        s_env.current_balance -= amount_dec
        tx = Transaction(
            user_id=user_id,
            envelope_id=s_env.id,
            amount=amount_dec,
            type=TransactionType.EMERGENCY_WITHDRAWAL,
            source=TransactionSource.MANUAL_TEXT,
            category="Форс-мажор / Подушка",
            merchant=req.reason
        )
        session.add(tx)
        await session.commit()
        new_balance = float(s_env.current_balance)

    return {"status": "OK", "new_savings_balance": new_balance}


# ---------------------------------------------------------------------------
# Фича 8: Долги (создание и закрытие)
# ---------------------------------------------------------------------------

@router.post("/api/me/debts")
async def create_debt(req: DebtCreateRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    amount_dec = Decimal(str(round(req.amount, 2)))
    dtype = DebtType(req.debt_type)

    async with async_session_maker() as session:
        debt = Debt(
            user_id=user_id,
            debt_type=dtype,
            person_name=req.person_name,
            amount=amount_dec,
            remaining_amount=amount_dec,
            comment=req.comment
        )
        session.add(debt)

        if dtype == DebtType.OWES_ME:
            env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.SAVINGS)
            s_env = (await session.execute(env_stmt)).scalar_one_or_none()
            if s_env:
                s_env.current_balance = max(s_env.current_balance - amount_dec, Decimal("0.00"))

        await session.commit()
    return {"status": "OK"}


@router.post("/api/me/debts/{debt_id}/close")
async def close_debt_api(debt_id: str, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    import uuid
    uid = uuid.UUID(debt_id)

    async with async_session_maker() as session:
        stmt = select(Debt).where(Debt.id == uid, Debt.user_id == user_id)
        debt = (await session.execute(stmt)).scalar_one_or_none()
        if not debt:
            raise HTTPException(status_code=404, detail="Долг не найден")

        debt.is_closed = True
        debt.closed_at = datetime.utcnow()

        if debt.debt_type == DebtType.OWES_ME:
            env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.SAVINGS)
            s_env = (await session.execute(env_stmt)).scalar_one_or_none()
            if s_env:
                s_env.current_balance += debt.remaining_amount

        await session.commit()
    return {"status": "OK"}


# ---------------------------------------------------------------------------
# Фича 6: Обязательства и Расходники
# ---------------------------------------------------------------------------

@router.post("/api/me/obligations")
async def create_obligation(req: ObligationCreateRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    amount_dec = Decimal(str(round(req.monthly_amount, 2)))
    otype = ObligationType(req.obligation_type)

    async with async_session_maker() as session:
        ob = Obligation(
            user_id=user_id,
            obligation_type=otype,
            title=req.title,
            monthly_amount=amount_dec,
            total_months=req.months_left,
            months_left=req.months_left,
            is_active=True
        )
        session.add(ob)
        await session.flush()

        # Recalculate total obligations and sync FIXED_COMMITMENT envelope
        oblg_stmt = select(Obligation).where(Obligation.user_id == user_id, Obligation.is_active == True)
        all_obls = (await session.execute(oblg_stmt)).scalars().all()
        total_oblg = sum((o.monthly_amount for o in all_obls), Decimal("0.00"))

        env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.FIXED_COMMITMENT)
        fix_env = (await session.execute(env_stmt)).scalar_one_or_none()
        if not fix_env:
            fix_env = Envelope(
                user_id=user_id,
                name="Обязательства и счета",
                type=EnvelopeType.FIXED_COMMITMENT,
                allocated_amount=total_oblg,
                current_balance=total_oblg
            )
            session.add(fix_env)
        else:
            fix_env.allocated_amount = total_oblg
            fix_env.current_balance = total_oblg

        await session.commit()
    return {"status": "OK"}


@router.delete("/api/me/obligations/{oblg_id}")
async def delete_obligation(oblg_id: str, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    import uuid
    uid = uuid.UUID(oblg_id)
    async with async_session_maker() as session:
        await session.execute(delete(Obligation).where(Obligation.id == uid, Obligation.user_id == user_id))
        await session.flush()

        # Recalculate total obligations and sync FIXED_COMMITMENT envelope
        oblg_stmt = select(Obligation).where(Obligation.user_id == user_id, Obligation.is_active == True)
        all_obls = (await session.execute(oblg_stmt)).scalars().all()
        total_oblg = sum((o.monthly_amount for o in all_obls), Decimal("0.00"))

        env_stmt = select(Envelope).where(Envelope.user_id == user_id, Envelope.type == EnvelopeType.FIXED_COMMITMENT)
        fix_env = (await session.execute(env_stmt)).scalar_one_or_none()
        if fix_env:
            fix_env.allocated_amount = total_oblg
            fix_env.current_balance = total_oblg

        await session.commit()
    return {"status": "OK"}


# ---------------------------------------------------------------------------
# Фича 5: Финансовые цели
# ---------------------------------------------------------------------------

@router.post("/api/me/goals")
async def create_goal(req: GoalCreateRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    target_dec = Decimal(str(round(req.target_amount, 2)))
    async with async_session_maker() as session:
        goal = Goal(
            user_id=user_id,
            title=req.title,
            target_amount=target_dec,
            current_amount=Decimal("0.00"),
            is_primary=True
        )
        session.add(goal)
        await session.commit()
    return {"status": "OK"}


# ---------------------------------------------------------------------------
# Фича 4: Напоминания о покупках
# ---------------------------------------------------------------------------

@router.post("/api/me/shopping-reminders")
async def create_shopping_reminder(req: ShoppingReminderRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    match = re.search(r"(\d{1,2})[:.-](\d{2})", req.time_str.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Укажите продукт или текст приема")

    h, m = int(match.group(1)), int(match.group(2))
    import pytz
    from datetime import timedelta
    msk = pytz.timezone("Europe/Moscow")
    now_msk = datetime.now(msk)
    target = now_msk.replace(hour=h, minute=m, second=0, microsecond=0)
    if target <= now_msk:
        target += timedelta(days=1)

    async with async_session_maker() as session:
        rem = ShoppingReminder(
            user_id=user_id,
            items_text=req.items,
            remind_at=target,
            is_sent=False
        )
        session.add(rem)
        await session.commit()
    return {"status": "OK", "remind_at": target.strftime("%H:%M (%d.%m)")}


# ---------------------------------------------------------------------------
# Фича 7: Рандомайзер
# ---------------------------------------------------------------------------

@router.post("/api/me/randomizer")
async def run_randomizer(req: RandomizerRequest, tg_user: dict = Depends(get_telegram_user)):
    res = decide_randomizer(req.item)
    return res


# ---------------------------------------------------------------------------
# ЗОЖ-модуль: Напоминания о зарядке и ПП-рецепты
# ---------------------------------------------------------------------------

@router.post("/api/me/habit-reminders")
async def create_habit_reminder(req: HabitReminderRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    match = re.search(r"(\d{1,2})[:.-](\d{2})", req.time_str.strip())
    if not match:
        raise HTTPException(status_code=400, detail="Укажите продукт или текст приема")

    h, m = int(match.group(1)), int(match.group(2))
    rem_time = dtime(hour=h, minute=m)
    htype = HabitType(req.habit_type)

    async with async_session_maker() as session:
        h_rem = HabitReminder(
            user_id=user_id,
            habit_type=htype,
            title=req.title,
            remind_time=rem_time,
            is_active=True
        )
        session.add(h_rem)
        await session.commit()
    return {"status": "OK"}


@router.delete("/api/me/habit-reminders/{rem_id}")
async def delete_habit_reminder(rem_id: str, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    import uuid
    uid = uuid.UUID(rem_id)
    async with async_session_maker() as session:
        await session.execute(delete(HabitReminder).where(HabitReminder.id == uid, HabitReminder.user_id == user_id))
        await session.commit()
    return {"status": "OK"}


@router.post("/api/me/recipes/generate")
async def get_pp_recipe(req: RecipeRequest, tg_user: dict = Depends(get_telegram_user)):
    recipe = generate_pp_recipe(req.ingredients)
    return recipe


# ---------------------------------------------------------------------------
# Settings & Health Profile
# ---------------------------------------------------------------------------

@router.post("/api/me/settings")
async def update_settings_from_app(req: SettingsRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.payday_day_of_month = req.payday_day
        user.savings_target_percent = Decimal(str(req.savings_percent))
        if req.show_hourly_rate is not None:
            user.show_hourly_rate = req.show_hourly_rate
        if req.roundtrip_commute_fare is not None:
            user.roundtrip_commute_fare = Decimal(str(round(req.roundtrip_commute_fare, 2)))
        if req.work_shifts_per_month is not None and req.work_shifts_per_month > 0:
            user.work_shifts_per_month = req.work_shifts_per_month
        if req.weight_kg is not None:
            user.weight_kg = Decimal(str(req.weight_kg))
        if req.target_weight_kg is not None:
            user.target_weight_kg = Decimal(str(req.target_weight_kg))
        if req.height_cm is not None:
            user.height_cm = req.height_cm

        await session.commit()

    return {"status": "OK"}


# ---------------------------------------------------------------------------
# ??? & ?????????: ??????? ???????, ??????? ??????? & ???? ??????????
# ---------------------------------------------------------------------------

@router.post("/api/me/food")
async def add_food_log(req: FoodLogCreateRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])

    food_name = req.food_name
    calories = req.calories
    proteins = req.proteins or 0.0
    fats = req.fats or 0.0
    carbs = req.carbs or 0.0
    source = req.source or "manual"

    if req.text and (calories is None or not food_name):
        parsed = parse_food_input(req.text)
        food_name = parsed["food_name"]
        calories = parsed["calories"]
        proteins = parsed["proteins"]
        fats = parsed["fats"]
        carbs = parsed["carbs"]
        if re.fullmatch(r"\d{8,14}", req.text.strip()):
            source = "barcode"

    if not food_name or calories is None:
        raise HTTPException(status_code=400, detail="Укажите продукт или текст приема")

    async with async_session_maker() as session:
        log_entry = FoodLog(
            user_id=user_id,
            food_name=food_name,
            calories=Decimal(str(round(calories, 2))),
            proteins=Decimal(str(round(proteins, 2))),
            fats=Decimal(str(round(fats, 2))),
            carbs=Decimal(str(round(carbs, 2))),
            source=source,
            logged_at=datetime.utcnow()
        )
        session.add(log_entry)
        await session.commit()
        await session.refresh(log_entry)
        entry_id = str(log_entry.id)

    return {
        "status": "OK",
        "entry": {
            "id": entry_id,
            "food_name": food_name,
            "calories": float(calories),
            "proteins": float(proteins),
            "fats": float(fats),
            "carbs": float(carbs),
            "source": source
        }
    }


@router.delete("/api/me/food/{food_id}")
async def delete_food_log(food_id: str, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    uid = uuid.UUID(food_id)
    async with async_session_maker() as session:
        await session.execute(delete(FoodLog).where(FoodLog.id == uid, FoodLog.user_id == user_id))
        await session.commit()
    return {"status": "OK"}


@router.post("/api/me/health-profile")
async def update_health_profile(req: HealthProfileRequest, tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    async with async_session_maker() as session:
        user_stmt = select(User).where(User.id == user_id)
        user = (await session.execute(user_stmt)).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.weight_kg = Decimal(str(round(req.weight_kg, 2)))
        user.target_weight_kg = Decimal(str(round(req.target_weight_kg, 2)))
        user.height_cm = req.height_cm
        user.age = req.age or 25
        user.gender = req.gender or "male"
        user.activity_level = req.activity_level or "moderate"

        plan = calculate_weight_loss_plan(
            current_weight=req.weight_kg,
            target_weight=req.target_weight_kg,
            height_cm=req.height_cm,
            age=user.age,
            gender=user.gender,
            activity_level=user.activity_level
        )
        user.daily_calorie_target = plan["target_calories"]

        await session.commit()

    return {"status": "OK", "weight_plan": plan}
