from datetime import date
from decimal import Decimal
from app.services.finance_engine import FinanceEngine


def test_salary_pipeline():
    result = FinanceEngine.process_salary_pipeline(
        salary=Decimal("2500.00"),
        work_shifts=22,
        roundtrip_commute_fare=Decimal("4.00"),
        fixed_commitments_total=Decimal("400.00"),
        savings_percent=Decimal("20.00"),
        today=date(2026, 11, 1),
        payday_day=10,
        working_hours=168
    )

    # Commute = 22 * 4 = 88.00
    assert result.commute_frozen == Decimal("88.00")
    # Fixed = 400.00
    assert result.fixed_commitments_frozen == Decimal("400.00")
    # Net Base = 2500 - (88 + 400) = 2012.00
    assert result.net_base == Decimal("2012.00")
    # Savings (20%) = 402.40
    assert result.savings_locked == Decimal("402.40")
    # Discretionary = 2012 - 402.40 = 1609.60
    assert result.discretionary_budget == Decimal("1609.60")
    # Days left to 10 Nov = 9 days
    assert result.days_in_cycle == 9
    # Daily safe spend = 1609.60 / 9 = 178.84
    assert result.daily_safe_spend == Decimal("178.84")
    # Hourly rate = 2012 / 168 = 11.98
    assert result.hourly_rate == Decimal("11.98")


def test_work_hours_paywall():
    res = FinanceEngine.calculate_work_hours_paywall(
        price=Decimal("350.00"),
        hourly_rate=Decimal("14.58"),
        item_name="Кроссовки"
    )
    # 350 / 14.58 = 24.0 hours
    assert res["hours"] == Decimal("24.0")
    # 24 / 8 = 3.0 days
    assert res["days"] == Decimal("3.0")
    assert "24.0 ч." in res["formatted_message"]


def test_crisis_mode_dampen():
    res = FinanceEngine.resolve_crisis_mode(
        overspent_amount=Decimal("50.00"),
        weekly_remaining_budget=Decimal("350.00"),
        remaining_days_in_week=5,
        weekend_fund_balance=Decimal("20.00"),
        strategy="DAMPEN_LIMITS"
    )
    # (350 - 50) / 5 = 60.00
    assert res.updated_daily_limit == Decimal("60.00")


def test_crisis_mode_weekend_fund():
    res = FinanceEngine.resolve_crisis_mode(
        overspent_amount=Decimal("30.00"),
        weekly_remaining_budget=Decimal("350.00"),
        remaining_days_in_week=5,
        weekend_fund_balance=Decimal("50.00"),
        strategy="COVER_BY_WEEKEND_FUND"
    )
    # Covered 30 from 50, leaves 20
    assert res.weekend_fund_remaining == Decimal("20.00")
    # Uncovered debt = 0, limit unchanged: 350 / 5 = 70.00
    assert res.updated_daily_limit == Decimal("70.00")


if __name__ == "__main__":
    test_salary_pipeline()
    test_work_hours_paywall()
    test_crisis_mode_dampen()
    test_crisis_mode_weekend_fund()
    print("All financial engine tests passed successfully!")
