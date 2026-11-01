-- =============================================================================
-- CACHEBOT: Zero-Based Budgeting Financial Architecture Schema
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enums
DO $$ BEGIN
    CREATE TYPE transaction_type AS ENUM (
        'EXPENSE',
        'INCOME',
        'TRANSFER_TO_CASH',
        'TRANSFER_TO_SAVINGS',
        'REALLOCATION'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE envelope_type AS ENUM (
        'FIXED_COMMITMENT',
        'COMMUTE',
        'SAVINGS',
        'WEEKEND_FUND',
        'DAILY_SAFE_SPEND'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE transaction_source AS ENUM (
        'MANUAL_TEXT',
        'VOICE_WHISPER',
        'VISION_RECEIPT',
        'VISION_BANK_STATEMENT'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 1. Users
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY, -- Telegram User ID
    username VARCHAR(64),
    first_name VARCHAR(128),
    currency VARCHAR(3) DEFAULT 'BYN' NOT NULL,
    
    monthly_working_hours INT DEFAULT 168 NOT NULL,
    work_shifts_per_month INT DEFAULT 22 NOT NULL,
    roundtrip_commute_fare NUMERIC(10, 2) DEFAULT 0.00 NOT NULL,
    
    payday_day_of_month INT DEFAULT 10 NOT NULL,
    savings_target_percent NUMERIC(5, 2) DEFAULT 20.00 NOT NULL,
    
    current_cycle_net_base NUMERIC(12, 2) DEFAULT 0.00 NOT NULL,
    current_hourly_rate NUMERIC(10, 2) DEFAULT 0.00 NOT NULL,
    daily_safe_spend_limit NUMERIC(10, 2) DEFAULT 0.00 NOT NULL,
    
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- 2. Envelopes
CREATE TABLE IF NOT EXISTS envelopes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(64) NOT NULL,
    type envelope_type NOT NULL,
    allocated_amount NUMERIC(12, 2) DEFAULT 0.00 NOT NULL,
    current_balance NUMERIC(12, 2) DEFAULT 0.00 NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    UNIQUE(user_id, type)
);

-- 3. Recurring Commitments
CREATE TABLE IF NOT EXISTS recurring_rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(128) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    category VARCHAR(64) NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- 4. Savings Goals
CREATE TABLE IF NOT EXISTS goals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(128) NOT NULL,
    target_amount NUMERIC(12, 2) NOT NULL,
    current_amount NUMERIC(12, 2) DEFAULT 0.00 NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- 5. Transactions
CREATE TABLE IF NOT EXISTS transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    envelope_id UUID REFERENCES envelopes(id) ON DELETE SET NULL,
    goal_id UUID REFERENCES goals(id) ON DELETE SET NULL,
    
    amount NUMERIC(12, 2) NOT NULL,
    type transaction_type NOT NULL,
    source transaction_source NOT NULL,
    
    category VARCHAR(64) NOT NULL,
    merchant VARCHAR(128),
    raw_input_text TEXT,
    is_needs_clarification BOOLEAN DEFAULT FALSE NOT NULL,
    
    executed_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transactions_user_date ON transactions(user_id, executed_at);
CREATE INDEX IF NOT EXISTS idx_transactions_envelope ON transactions(envelope_id);
