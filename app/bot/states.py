from aiogram.fsm.state import StatesGroup, State


class IncomeFSM(StatesGroup):
    waiting_for_amount = State()
    waiting_for_type = State()
    waiting_for_payday = State()
    waiting_for_custom_date = State()


class PaywallFSM(StatesGroup):
    waiting_for_item_or_price = State()


class SettingsFSM(StatesGroup):
    waiting_for_commute_fare = State()
    waiting_for_shifts = State()


class DebtFSM(StatesGroup):
    waiting_for_person = State()
    waiting_for_amount = State()
    waiting_for_comment = State()


class EmergencyWithdrawFSM(StatesGroup):
    waiting_for_amount = State()
    waiting_for_reason = State()


class ObligationFSM(StatesGroup):
    waiting_for_title = State()
    waiting_for_monthly_amount = State()
    waiting_for_months_left = State()


class ShoppingReminderFSM(StatesGroup):
    waiting_for_items = State()
    waiting_for_time = State()  # время в формате ЧЧ:ММ (МСК)


class RandomizerFSM(StatesGroup):
    waiting_for_item = State()
