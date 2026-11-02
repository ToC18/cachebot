@router.get("/api/me/dashboard")
async def get_user_dashboard(tg_user: dict = Depends(get_telegram_user)):
    user_id = int(tg_user["id"])
    today = date.today()

    try:
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
                    current_cycle_net_base=Decimal("0.00"),
                    current_hourly_rate=Decimal("0.00"),
                    daily_safe_spend_limit=Decimal("0.00"),
                    show_hourly_rate=True
                )
                session.add(user)
                await session.commit()
                # Re-select to ensure all defaults are loaded
                user = (await session.execute(user_stmt)).scalar_one()

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
                category_breakdown[clean_name] = category_breakdown.get(clean_name, 0.0) + float(t.amount or 0.0)

            # Debts
            debts_stmt = select(Debt).where(Debt.user_id == user_id, Debt.is_closed == False)
            active_debts = (await session.execute(debts_stmt)).scalars().all()
            i_owe_list = [
                {"id": str(d.id), "person": d.person_name, "amount": float(d.remaining_amount or 0.0), "comment": d.comment or ""}
                for d in active_debts if d.debt_type == DebtType.I_OWE
            ]
            owes_me_list = [
                {"id": str(d.id), "person": d.person_name, "amount": float(d.remaining_amount or 0.0), "comment": d.comment or ""}
                for d in active_debts if d.debt_type == DebtType.OWES_ME
            ]

            # Obligations (Credits + Consumables)
            oblg_stmt = select(Obligation).where(Obligation.user_id == user_id, Obligation.is_active == True)
            obls = (await session.execute(oblg_stmt)).scalars().all()
            obligations_list = [
                {
                    "id": str(o.id),
                    "title": o.title,
                    "amount": float(o.monthly_amount or 0.0),
                    "type": o.obligation_type.value if hasattr(o.obligation_type, "value") else str(o.obligation_type),
                    "months_left": o.months_left
                }
                for o in obls
            ]

            # Goals + ETA
            base_salary = user.current_cycle_net_base or Decimal("0.00")
            savings_pct = user.savings_target_percent or Decimal("20.00")
            monthly_savings = (base_salary * (savings_pct / Decimal("100.00"))).quantize(Decimal("0.01"))
            goals_stmt = select(Goal).where(Goal.user_id == user_id)
            goals = (await session.execute(goals_stmt)).scalars().all()
            goals_list = []
            for g in goals:
                eta = estimate_goal_months(g.target_amount or Decimal("0.00"), g.current_amount or Decimal("0.00"), monthly_savings)
                goals_list.append({
                    "id": str(g.id),
                    "title": g.title,
                    "target": float(g.target_amount or 0.0),
                    "current": float(g.current_amount or 0.0),
                    "months_left": eta.get("months", 0),
                    "eta_text": eta.get("formatted", "")
                })

            # Shopping reminders
            shop_stmt = select(ShoppingReminder).where(ShoppingReminder.user_id == user_id, ShoppingReminder.is_sent == False)
            shop_reminders = (await session.execute(shop_stmt)).scalars().all()
            shopping_list = [
                {
                    "id": str(s.id),
                    "items": s.items_text,
                    "time": s.remind_at.strftime("%H:%M (%d.%m)") if s.remind_at else ""
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
                    "type": h.habit_type.value if hasattr(h.habit_type, "value") else str(h.habit_type),
                    "time": h.remind_time.strftime("%H:%M") if h.remind_time else ""
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
                    "calories": float(f.calories or 0.0),
                    "proteins": float(f.proteins or 0.0),
                    "fats": float(f.fats or 0.0),
                    "carbs": float(f.carbs or 0.0),
                    "source": f.source,
                    "time": f.logged_at.strftime("%H:%M") if f.logged_at else ""
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
                payday_day=user.payday_day_of_month or 10
            )

            has_budget = bool(user.daily_safe_spend_limit and user.daily_safe_spend_limit > Decimal("0.00"))
            total_oblg_sum = sum(float(o["amount"]) for o in obligations_list)
            fixed_env = envelopes.get(EnvelopeType.FIXED_COMMITMENT)
            fixed_env_bal = float(fixed_env.current_balance) if (fixed_env and fixed_env.current_balance is not None) else 0.0
            effective_fixed = max(fixed_env_bal, total_oblg_sum)

            def get_env_bal(env_type):
                env = envelopes.get(env_type)
                return float(env.current_balance) if (env and env.current_balance is not None) else 0.0

            return {
                "user_id": user_id,
                "first_name": user.first_name or tg_user.get("first_name") or "Друг",
                "currency": user.currency or "BYN",
                "has_budget": has_budget,
                "show_hourly_rate": bool(user.show_hourly_rate),
                "roundtrip_commute_fare": float(user.roundtrip_commute_fare or 0.0),
                "work_shifts": user.work_shifts_per_month or 22,
                "daily_safe_spend_limit": float(user.daily_safe_spend_limit or 0.0),
                "today_spent": float(today_spent or 0.0),
                "current_hourly_rate": float(user.current_hourly_rate or 0.0),
                "days_left": days_left,
                "payday_day_of_month": user.payday_day_of_month or 10,
                "savings_target_percent": float(user.savings_target_percent or 20.0),
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
                    "savings": get_env_bal(EnvelopeType.SAVINGS),
                    "weekend_fund": get_env_bal(EnvelopeType.WEEKEND_FUND),
                    "commute": get_env_bal(EnvelopeType.COMMUTE),
                    "fixed_commitment": round(effective_fixed, 2),
                    "daily_safe_spend": get_env_bal(EnvelopeType.DAILY_SAFE_SPEND),
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
    except Exception as e:
        import logging
        logging.getLogger("cachebot").error(f"Error serving /api/me/dashboard: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
