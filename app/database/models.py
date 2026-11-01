import uuid
from datetime import datetime, date, time as dtime
from decimal import Decimal
import enum
from sqlalchemy import (
    BigInteger,
    Column,
    String,
    Integer,
    Numeric,
    Boolean,
    DateTime,
    Date,
    Time,
    ForeignKey,
    Text,
    Enum,
    UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class TransactionType(str, enum.Enum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"
    TRANSFER_TO_CASH = "TRANSFER_TO_CASH"
    TRANSFER_TO_SAVINGS = "TRANSFER_TO_SAVINGS"
    REALLOCATION = "REALLOCATION"
    EMERGENCY_WITHDRAWAL = "EMERGENCY_WITHDRAWAL"


class EnvelopeType(str, enum.Enum):
    FIXED_COMMITMENT = "FIXED_COMMITMENT"
    COMMUTE = "COMMUTE"
    SAVINGS = "SAVINGS"
    WEEKEND_FUND = "WEEKEND_FUND"
    DAILY_SAFE_SPEND = "DAILY_SAFE_SPEND"
    CONSUMABLES = "CONSUMABLES"


class TransactionSource(str, enum.Enum):
    MANUAL_TEXT = "MANUAL_TEXT"
    VOICE_WHISPER = "VOICE_WHISPER"
    VISION_RECEIPT = "VISION_RECEIPT"
    VISION_BANK_STATEMENT = "VISION_BANK_STATEMENT"


class DebtType(str, enum.Enum):
    I_OWE = "I_OWE"
    OWES_ME = "OWES_ME"


class ObligationType(str, enum.Enum):
    INSTALLMENT = "INSTALLMENT"
    CREDIT = "CREDIT"
    SUBSCRIPTION = "SUBSCRIPTION"
    CONSUMABLE = "CONSUMABLE"


class HabitType(str, enum.Enum):
    WARMUP = "WARMUP"
    WORKOUT = "WORKOUT"
    WATER = "WATER"
    STRETCH = "STRETCH"


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)  # Telegram User ID
    username = Column(String(64), nullable=True)
    first_name = Column(String(128), nullable=True)
    currency = Column(String(3), default="BYN", nullable=False)

    monthly_working_hours = Column(Integer, default=168, nullable=False)
    work_shifts_per_month = Column(Integer, default=22, nullable=False)
    roundtrip_commute_fare = Column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)

    payday_day_of_month = Column(Integer, default=10, nullable=False)
    next_payday_date = Column(Date, nullable=True)
    savings_target_percent = Column(Numeric(5, 2), default=Decimal("20.00"), nullable=False)

    current_cycle_net_base = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    current_hourly_rate = Column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    daily_safe_spend_limit = Column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)

    show_hourly_rate = Column(Boolean, default=True, nullable=False)

    # ЗОЖ и похудение
    weight_kg = Column(Numeric(5, 2), nullable=True)
    target_weight_kg = Column(Numeric(5, 2), nullable=True)
    height_cm = Column(Integer, nullable=True)
    age = Column(Integer, default=25, nullable=True)
    gender = Column(String(10), default="male", nullable=True)  # "male" or "female"
    activity_level = Column(String(20), default="moderate", nullable=True)  # "sedentary", "light", "moderate", "high"
    daily_calorie_target = Column(Integer, default=1800, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    envelopes = relationship("Envelope", back_populates="user", cascade="all, delete-orphan")
    recurring_rules = relationship("RecurringRule", back_populates="user", cascade="all, delete-orphan")
    goals = relationship("Goal", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    debts = relationship("Debt", back_populates="user", cascade="all, delete-orphan")
    obligations = relationship("Obligation", back_populates="user", cascade="all, delete-orphan")
    shopping_reminders = relationship("ShoppingReminder", back_populates="user", cascade="all, delete-orphan")
    habit_reminders = relationship("HabitReminder", back_populates="user", cascade="all, delete-orphan")
    food_logs = relationship("FoodLog", back_populates="user", cascade="all, delete-orphan")


class Envelope(Base):
    __tablename__ = "envelopes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(64), nullable=False)
    type = Column(Enum(EnvelopeType, name="envelope_type", create_type=False), nullable=False)
    allocated_amount = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    current_balance = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="envelopes")
    transactions = relationship("Transaction", back_populates="envelope")

    __table_args__ = (UniqueConstraint("user_id", "type", name="uq_user_envelope_type"),)


class RecurringRule(Base):
    __tablename__ = "recurring_rules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(128), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    category = Column(String(64), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="recurring_rules")


class Goal(Base):
    __tablename__ = "goals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(128), nullable=False)
    target_amount = Column(Numeric(12, 2), nullable=False)
    current_amount = Column(Numeric(12, 2), default=Decimal("0.00"), nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="goals")
    transactions = relationship("Transaction", back_populates="goal")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    envelope_id = Column(UUID(as_uuid=True), ForeignKey("envelopes.id", ondelete="SET NULL"), nullable=True)
    goal_id = Column(UUID(as_uuid=True), ForeignKey("goals.id", ondelete="SET NULL"), nullable=True)

    amount = Column(Numeric(12, 2), nullable=False)
    type = Column(Enum(TransactionType, name="transaction_type", create_type=False), nullable=False)
    source = Column(Enum(TransactionSource, name="transaction_source", create_type=False), nullable=False)

    category = Column(String(64), nullable=False)
    merchant = Column(String(128), nullable=True)
    raw_input_text = Column(Text, nullable=True)
    is_needs_clarification = Column(Boolean, default=False, nullable=False)

    executed_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="transactions")
    envelope = relationship("Envelope", back_populates="transactions")
    goal = relationship("Goal", back_populates="transactions")


class Debt(Base):
    __tablename__ = "debts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    debt_type = Column(Enum(DebtType, name="debt_type", create_type=False), nullable=False)
    person_name = Column(String(128), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    remaining_amount = Column(Numeric(12, 2), nullable=False)
    comment = Column(String(256), nullable=True)
    is_closed = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    closed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="debts")


class Obligation(Base):
    __tablename__ = "obligations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    obligation_type = Column(Enum(ObligationType, name="obligation_type", create_type=False), nullable=False)
    title = Column(String(128), nullable=False)
    monthly_amount = Column(Numeric(12, 2), nullable=False)
    total_months = Column(Integer, nullable=True)
    months_left = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="obligations")


class ShoppingReminder(Base):
    __tablename__ = "shopping_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    items_text = Column(Text, nullable=False)
    remind_at = Column(DateTime(timezone=True), nullable=False)
    is_sent = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="shopping_reminders")


class HabitReminder(Base):
    __tablename__ = "habit_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    habit_type = Column(Enum(HabitType, name="habit_type", create_type=False), nullable=False)
    title = Column(String(128), nullable=False)
    remind_time = Column(Time, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    days_of_week = Column(String(32), default="all", nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="habit_reminders")


class FoodLog(Base):
    """Дневник питания: блюдо/продукт, калории и БЖУ."""
    __tablename__ = "food_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    food_name = Column(String(256), nullable=False)
    calories = Column(Numeric(8, 2), nullable=False)
    proteins = Column(Numeric(8, 2), default=Decimal("0.00"), nullable=False)
    fats = Column(Numeric(8, 2), default=Decimal("0.00"), nullable=False)
    carbs = Column(Numeric(8, 2), default=Decimal("0.00"), nullable=False)
    source = Column(String(32), default="manual", nullable=False)  # manual, barcode, quick

    logged_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="food_logs")
